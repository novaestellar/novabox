"""Blackbox.ai Farm — Modern Dashboard TUI."""
from __future__ import annotations

import asyncio
import io
import json
import os
import secrets
import string
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
load_dotenv()

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.columns import Columns
from rich.layout import Layout
from rich.live import Live
from rich import box

from config import Config
from dashboard import FarmDashboard
from exporter import export_all
from injector import inject_keys, find_9router_db, list_injected, remove_keys
from models import WORKING_MODELS, test_all
from providers.blackbox import AccountResult, BlackboxClient
from providers.tempmail import generate_email

STATE_FILE = "state.json"
console = Console(width=60)

# ─── Helpers ──────────────────────────────────────────────────────────

def generate_password(length=16):
    return "".join(secrets.choice(string.ascii_letters + string.digits + "!@#$%") for _ in range(length))

def load_state(output_dir):
    p = Path(output_dir) / STATE_FILE
    if not p.exists(): return {"target": 0, "accounts": []}
    try: return json.loads(p.read_text(encoding="utf-8"))
    except: return {"target": 0, "accounts": []}

def save_state(output_dir, state):
    p = Path(output_dir) / STATE_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

def append_key(output_dir, record):
    p = Path(output_dir) / "keys.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(f"{record['email']}:{record['password']}:{record['api_key']}\n")

def done_emails(state):
    return {a.get("email", "") for a in state.get("accounts", []) if a.get("success")}

def count_keys():
    p = Path("output/keys.txt")
    if not p.exists(): return 0
    return len([l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()])

def _first_key():
    p = Path("output/keys.txt")
    if not p.exists(): return ""
    for line in p.read_text(encoding="utf-8").splitlines():
        parts = line.split(":")
        if len(parts) >= 3 and parts[2].strip(): return parts[2].strip()
    return ""

def wait_key(prompt="Press Enter to continue..."):
    console.print(f"\n  {prompt}", end="")
    try: input()
    except: pass

def clear():
    os.system("cls" if os.name == "nt" else "clear")

# ─── Visual Components ────────────────────────────────────────────────

def progress_bar(percent, width=30, color="green"):
    filled = int(width * min(percent, 1.0))
    empty = width - filled
    return f"[{color}]{'=' * filled}[/{color}][dim]{'-' * empty}[/dim]"

def mini_chart(values, width=20):
    if not values: return "[dim]No data[/dim]"
    max_val = max(values) if max(values) > 0 else 1
    bars = []
    for v in values[-width:]:
        h = int((v / max_val) * 4) if v > 0 else 0
        bars.append([" ", ".", "o", "O", "#"][h])
    return "".join(bars)

def draw_dashboard():
    clear()
    state = load_state("output")
    accounts = state.get("accounts", [])
    ok = len([a for a in accounts if a.get("success")])
    fail = len([a for a in accounts if not a.get("success")])
    total = state.get("target", 0)
    keys = count_keys()
    db = find_9router_db()

    # Header
    console.print(Panel(
        Text("BLACKBOX.AI FARM", style="bold white", justify="center"),
        subtitle="AI Model Farm Tool v2.1 | 32 Free Models",
        box=box.DOUBLE,
        border_style="cyan",
    ))

    # Stats row
    stats = Table(box=None, show_header=False, padding=(0, 2))
    stats.add_column("k", style="dim")
    stats.add_column("v", style="bold")
    stats.add_row("Keys", str(keys))
    stats.add_row("[green]Success[/green]", f"[green]{ok}[/green]")
    stats.add_row("[red]Failed[/red]", f"[red]{fail}[/red]")
    stats.add_row("DB", "Connected" if db else "Not found")
    console.print(stats)
    console.print()

    # Progress
    if total > 0:
        pct = min(ok / total, 1.0)
        console.print(f"  Registration: {progress_bar(pct)} {ok}/{total} ({int(pct*100)}%)")
    else:
        console.print("  Registration: No data yet")
    console.print()

    # Recent activity
    recent = accounts[-20:] if accounts else []
    if recent:
        chart = " ".join(["[green]#[/green]" if a.get("success") else "[red]X[/red]" for a in recent])
        console.print(f"  Last {len(recent)}: {chart}")
        console.print()

    # Menu
    console.print("  MAIN MENU")
    console.print("  " + "-" * 56)
    console.print("  1  REGISTER      Register new accounts & harvest API keys")
    console.print("  2  TEST MODELS   Check which AI models are working")
    console.print("  3  VIEW KEYS     Show all harvested API keys")
    console.print("  4  EXPORT        Export keys to file (TXT/JSON/CSV)")
    console.print("  5  INJECT DB     Push keys into 9router database")
    console.print("  6  STATUS        Show detailed registration history")
    console.print("  7  VALIDATE KEYS Test all keys and clean dead ones")
    console.print("  8  QUIT          Exit application")
    console.print("  " + "-" * 56)

# ─── Main Menu ────────────────────────────────────────────────────────

def main_menu():
    while True:
        draw_dashboard()
        try:
            raw = input("\n  Select [1-8]: ").strip()
        except (EOFError, KeyboardInterrupt):
            return "quit"
        if raw in ("1",): return "reg"
        elif raw in ("2",): return "test"
        elif raw in ("3",): return "keys"
        elif raw in ("4",): return "export"
        elif raw in ("5",): return "inject"
        elif raw in ("6",): return "status"
        elif raw in ("7",): return "validate"
        elif raw in ("8", "q", "x"): return "quit"

# ─── Register ─────────────────────────────────────────────────────────

def menu_register():
    count = 10
    workers = 3
    headless = True
    domain = "random"
    state = load_state("output")
    done = len(done_emails(state))

    while True:
        clear()
        console.print(Panel("REGISTER ACCOUNTS", box=box.DOUBLE, border_style="green"))
        if done > 0:
            console.print(f"  Previously completed: {done} accounts\n")

        settings = Table(box=None, show_header=False, padding=(0, 2))
        settings.add_column("k", style="dim", width=15)
        settings.add_column("v", style="bold")
        settings.add_row("Count:", str(count))
        settings.add_row("Workers:", str(workers))
        settings.add_row("Headless:", "[green]ON[/green]" if headless else "[red]OFF[/red]")
        settings.add_row("Domain:", domain)
        console.print(Panel(settings, title="SETTINGS", border_style="cyan"))

        actions = Table(box=None, show_header=False, padding=(0, 2))
        actions.add_column("num", style="bold green", width=4)
        actions.add_column("cmd", style="bold white", width=18)
        actions.add_column("desc", style="dim")
        actions.add_row("1", "START NEW", "Register fresh accounts")
        if done > 0:
            actions.add_row("2", "RESUME", f"Continue from {done} previous accounts")
        actions.add_row("3", "CHANGE COUNT", f"Number of accounts (current: {count})")
        actions.add_row("4", "CHANGE WORKERS", f"Concurrent browsers (current: {workers})")
        actions.add_row("5", "TOGGLE HEADLESS", f"Browser visible (current: {'OFF' if headless else 'ON'})")
        actions.add_row("6", "CHANGE DOMAIN", f"Email domain (current: {domain} | 'random')")
        actions.add_row("7", "BACK", "Return to main menu")
        console.print(Panel(actions, title="ACTIONS", border_style="green"))

        try:
            raw = input("\n  Select: ").strip()
        except (EOFError, KeyboardInterrupt):
            return

        if raw == "1":
            _do_register(count, workers, headless, domain, resume=False)
            return
        elif raw == "2" and done > 0:
            _do_register(count, workers, headless, domain, resume=True)
            return
        elif raw == "3":
            val = input(f"  Count [{count}]: ").strip()
            if val.isdigit(): count = max(1, int(val))
        elif raw == "4":
            val = input(f"  Workers [{workers}]: ").strip()
            if val.isdigit(): workers = max(1, int(val))
        elif raw == "5":
            headless = not headless
        elif raw == "6":
            val = input(f"  Domain [{domain}]: ").strip()
            if val: domain = val
        elif raw in ("7", "q", "x", "b"):
            return

def _do_register(count, workers, headless, domain, resume=False):
    cfg = Config(max_workers=workers, headless=headless, tempmail_domain=domain)
    state = load_state(cfg.output_dir)

    if resume:
        already = done_emails(state)
        remaining = max(0, count - len(already))
        if remaining == 0:
            console.print(f"  All {count} accounts already done.")
            wait_key()
            return
        console.print(f"  Resuming: {len(already)} done, {remaining} remaining")
        count = remaining

    dashboard = FarmDashboard(total=count, max_workers=workers)
    dashboard.start()
    try:
        asyncio.run(_drive(cfg, count, dashboard, state))
    except KeyboardInterrupt:
        pass
    finally:
        dashboard.stop()
        accounts = state.get("accounts", [])
        ok = [a for a in accounts if a.get("success")]
        console.print(f"\n  Done: {len(ok)} succeeded, {len(accounts) - len(ok)} failed")

        if ok:
            db = find_9router_db()
            if db:
                try:
                    injected = inject_keys("output/keys.txt", str(db))
                    console.print(f"  Auto-injected {injected} keys to 9router database")
                except Exception as e:
                    console.print(f"  Auto-inject failed: {e}")

        wait_key()

async def _drive(cfg, count, dashboard, state):
    sem = asyncio.Semaphore(cfg.max_workers)
    launched = 0
    tasks = []
    skip = done_emails(state)

    async def _account(wid, email, password):
        async with sem:
            result = AccountResult(email=email, password=password)
            start = time.monotonic()
            client = None
            dashboard.update_worker(wid, status="registering", email=email, started_at=start, error="", done=False, step="starting...")
            try:
                client = BlackboxClient(cfg)
                await client.start()
                
                def step_cb(step_name):
                    dashboard.update_worker(wid, step=step_name)
                    
                api_key = await client.register_and_create_key(email, password, on_step=step_cb)
                result.api_key = api_key
                result.success = True
            except Exception as e:
                result.error = str(e)[:200]
            finally:
                if client:
                    try: await client.stop()
                    except: pass
                result.elapsed = time.monotonic() - start
                dashboard.finish_worker(wid, success=result.success, error=result.error)
                record = {"email": result.email, "password": result.password,
                         "api_key": result.api_key, "success": result.success,
                         "error": result.error, "elapsed": round(result.elapsed, 2)}
                state["accounts"].append(record)
                state["target"] = count
                save_state(cfg.output_dir, state)
                if result.api_key:
                    append_key(cfg.output_dir, record)

    while launched < count:
        email = generate_email(cfg.tempmail_domain)
        while email in skip:
            email = generate_email(cfg.tempmail_domain)
        password = generate_password()
        tasks.append(asyncio.create_task(_account(launched % cfg.max_workers, email, password)))
        launched += 1
        await asyncio.sleep(secrets.SystemRandom().uniform(*cfg.delay_range))

    await asyncio.gather(*tasks, return_exceptions=True)

# ─── Test Models ──────────────────────────────────────────────────────

def menu_test():
    clear()
    console.print(Panel("TEST MODELS", box=box.DOUBLE, border_style="blue"))

    key = _first_key()
    if key:
        console.print(f"  Using key: {key[:20]}...")
    else:
        key = input("  API Key: ").strip()
        if not key:
            console.print("  No key provided")
            wait_key()
            return

    models = WORKING_MODELS[:32]
    console.print(f"\n  Testing {len(models)} models...\n")

    results = []
    ok_count = 0
    fail_count = 0

    for i, model in enumerate(models, 1):
        console.print(f"  [{i:2d}/{len(models)}] {model:<45}", end="")

        try:
            test_results = asyncio.run(test_all(key, [model]))
            if test_results and test_results[0].ok:
                console.print("[green][OK][/green]")
                ok_count += 1
                results.append({"model": model, "ok": True})
            else:
                console.print("[red][FAIL][/red]")
                fail_count += 1
                results.append({"model": model, "ok": False, "error": test_results[0].detail if test_results else "unknown"})
        except Exception as e:
            console.print(f"[red][ERR][/red] {str(e)[:30]}")
            fail_count += 1
            results.append({"model": model, "ok": False, "error": str(e)[:50]})

        pct = i / len(models)
        console.print(f"  Progress: {progress_bar(pct)} {i}/{len(models)} ({int(pct*100)}%)\n")

    console.print("\n" + "=" * 76)
    console.print(f"  RESULTS: {ok_count} OK / {fail_count} FAIL")
    console.print(f"  Success Rate: {progress_bar(ok_count/len(models))} {int(ok_count/len(models)*100)}%")
    console.print("=" * 76 + "\n")

    table = Table(box=box.ROUNDED, show_header=True, border_style="blue")
    table.add_column("Status", width=8)
    table.add_column("Model", width=40)
    for r in results:
        table.add_row("[green]OK[/green]" if r["ok"] else "[red]ERR[/red]", r["model"])
    console.print(table)

    Path("output").mkdir(exist_ok=True)
    Path("output/model_test.json").write_text(json.dumps({
        "ok": [r["model"] for r in results if r["ok"]],
        "fail": [{"model": r["model"], "error": r.get("error", "")} for r in results if not r["ok"]],
    }, indent=2), encoding="utf-8")
    wait_key()

# ─── View Keys ────────────────────────────────────────────────────────

def menu_keys():
    clear()
    console.print(Panel("HARVESTED KEYS", box=box.DOUBLE, border_style="yellow"))

    p = Path("output/keys.txt")
    if not p.exists():
        console.print("  No keys found. Run register first.")
        wait_key()
        return

    lines = [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    console.print(f"  Total: {len(lines)} keys\n")

    table = Table(box=box.ROUNDED, show_header=True, border_style="yellow")
    table.add_column("#", width=4, style="dim")
    table.add_column("Email", width=30)
    table.add_column("API Key", width=30, style="cyan")

    for i, line in enumerate(lines[:50], 1):
        parts = line.split(":")
        if len(parts) >= 3:
            table.add_row(str(i), parts[0][:28], parts[2][:25] + "...")

    if len(lines) > 50:
        console.print(f"  ... and {len(lines) - 50} more")

    console.print(table)
    wait_key()

# ─── Export ────────────────────────────────────────────────────────────

def menu_export():
    clear()
    console.print(Panel("EXPORT KEYS", box=box.DOUBLE, border_style="magenta"))

    state = load_state("output")
    accounts = [a for a in state.get("accounts", []) if a.get("api_key")]
    if not accounts:
        console.print("  No successful accounts to export.")
        wait_key()
        return

    console.print(f"  {len(accounts)} accounts ready\n")

    menu = Table(box=None, show_header=False, padding=(0, 2))
    menu.add_column("num", style="bold magenta", width=4)
    menu.add_column("cmd", style="bold white", width=18)
    menu.add_column("desc", style="dim")
    menu.add_row("1", "TXT", "Plain text format")
    menu.add_row("2", "JSON", "Structured JSON")
    menu.add_row("3", "CSV", "Spreadsheet format")
    menu.add_row("4", "ALL", "Export all formats")
    menu.add_row("5", "BACK", "Return to main menu")
    console.print(Panel(menu, title="EXPORT OPTIONS", border_style="magenta"))

    try:
        raw = input("\n  Select: ").strip()
    except (EOFError, KeyboardInterrupt):
        return

    if raw in ("1", "2", "3", "4"):
        written = export_all("output", accounts)
        console.print()
        for fmt, path in written.items():
            console.print(f"  {fmt.upper()} -> {path}")
        wait_key()
    elif raw in ("5", "q", "x", "b"):
        return

# ─── Inject to Database ───────────────────────────────────────────────

def menu_inject():
    clear()
    console.print(Panel("INJECT TO 9ROUTER", box=box.DOUBLE, border_style="yellow"))

    db = find_9router_db()
    if not db:
        console.print("  Database not found!")
        console.print("  Set PROVIDER_DB_PATH in .env file")
        wait_key()
        return

    p = Path("output/keys.txt")
    if not p.exists():
        console.print("  No keys to inject. Run register first.")
        wait_key()
        return

    lines = [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    existing = list_injected(str(db))

    while True:
        clear()
        console.print(Panel("INJECT TO 9ROUTER", box=box.DOUBLE, border_style="yellow"))

        stats = Table(box=None, show_header=False, padding=(0, 2))
        stats.add_column("k", style="dim", width=20)
        stats.add_column("v", style="bold")
        stats.add_row("DB:", db)
        stats.add_row("Keys ready:", str(len(lines)))
        stats.add_row("Already injected:", str(len(existing)))
        console.print(stats)

        menu = Table(box=None, show_header=False, padding=(0, 2))
        menu.add_column("num", style="bold yellow", width=4)
        menu.add_column("cmd", style="bold white", width=18)
        menu.add_column("desc", style="dim")
        menu.add_row("1", "INJECT ALL", "Push all keys to database")
        menu.add_row("2", "VIEW INJECTED", "Show keys already in database")
        menu.add_row("3", "REMOVE ALL", "Delete all keys from database")
        menu.add_row("4", "BACK", "Return to main menu")
        console.print(Panel(menu, title="ACTIONS", border_style="yellow"))

        try:
            raw = input("\n  Select: ").strip()
        except (EOFError, KeyboardInterrupt):
            return

        if raw == "1":
            try:
                count = inject_keys("output/keys.txt", str(db))
                console.print(f"\n  Injected {count} new keys!")
                existing = list_injected(str(db))
            except Exception as e:
                console.print(f"\n  Error: {e}")
            wait_key()
        elif raw == "2":
            clear()
            console.print(Panel("INJECTED KEYS", box=box.DOUBLE, border_style="yellow"))
            existing = list_injected(str(db))
            if not existing:
                console.print("  No keys in database.")
            else:
                table = Table(box=box.ROUNDED, show_header=True, border_style="yellow")
                table.add_column("#", width=4, style="dim")
                table.add_column("ID", width=25)
                table.add_column("Email", width=30)
                for i, row in enumerate(existing, 1):
                    table.add_row(str(i), row.get("id", "")[:23], row.get("email", "")[:28])
                console.print(table)
            wait_key()
        elif raw == "3":
            count = remove_keys(str(db))
            console.print(f"\n  Removed {count} keys.")
            existing = list_injected(str(db))
            wait_key()
        elif raw in ("4", "q", "x", "b"):
            return

# ─── Status ────────────────────────────────────────────────────────────

def menu_status():
    clear()
    console.print(Panel("RUN STATUS", box=box.DOUBLE, border_style="cyan"))

    state = load_state("output")
    accounts = state.get("accounts", [])
    ok = [a for a in accounts if a.get("success")]
    failed = [a for a in accounts if not a.get("success")]

    stats = Table(box=None, show_header=False, padding=(0, 3))
    stats.add_column("k", style="dim", width=20)
    stats.add_column("v", justify="right", width=10)
    stats.add_row("Target", str(state.get("target", 0)))
    stats.add_row("[green]Success[/green]", f"[green]{len(ok)}[/green]")
    stats.add_row("[red]Failed[/red]", f"[red]{len(failed)}[/red]")
    stats.add_row("Keys on disk", str(count_keys()))
    console.print(Panel(stats, title="STATISTICS", border_style="cyan"))

    if failed:
        console.print("\n  Recent failures:")
        for a in failed[-5:]:
            console.print(f"    {a.get('email', '?')[:28]}: {a.get('error', '?')[:40]}")

    wait_key()

# ─── Validate Keys ──────────────────────────────────────────────────────

def menu_validate():
    clear()
    console.print(Panel("VALIDATE & CLEAN KEYS", box=box.DOUBLE, border_style="red"))
    
    p = Path("output/keys.txt")
    if not p.exists():
        console.print("  No keys found to validate.")
        wait_key()
        return

    lines = p.read_text(encoding="utf-8").splitlines()
    records = []
    for line in lines:
        if line.strip():
            parts = line.split(":")
            if len(parts) >= 3:
                records.append(line)
                
    if not records:
        console.print("  No valid keys found in keys.txt.")
        wait_key()
        return

    console.print(f"  Found {len(records)} keys. Starting validation...\n")
    
    alive = []
    dead = []
    
    async def _validate_all():
        sem = asyncio.Semaphore(10)
        from models import test_model
        
        results_cache = {}
        next_to_print = [1]
        
        async def _test_key(line, i):
            parts = line.split(":")
            email, key = parts[0], parts[2].strip()
            
            async with sem:
                res = await test_model(key, "blackboxai/blackbox-pro", timeout=15)
                
                if res.ok:
                    alive.append(line)
                    status_str = "[green][OK][/green]"
                else:
                    dead.append(line)
                    status_str = f"[red][DEAD][/red] {res.detail[:30]}"
                    
                results_cache[i] = f"  [{i:3d}/{len(records)}] {email[:25]:<25} {status_str}"
                
                # Print strictly in original order
                while next_to_print[0] in results_cache:
                    console.print(results_cache[next_to_print[0]])
                    del results_cache[next_to_print[0]]
                    next_to_print[0] += 1
        
        tasks = [asyncio.create_task(_test_key(line, i)) for i, line in enumerate(records, 1)]
        await asyncio.gather(*tasks)
        
    asyncio.run(_validate_all())
    
    console.print("\n" + "=" * 56)
    console.print(f"  RESULTS: {len(alive)} ALIVE / {len(dead)} DEAD")
    console.print("=" * 56 + "\n")
    
    if dead:
        console.print(f"  Removing {len(dead)} dead keys from output/keys.txt...")
        p.write_text("\n".join(alive) + "\n", encoding="utf-8")
        console.print("  Done!")
    else:
        console.print("  All keys are working perfectly!")
        
    wait_key()

# ─── Main ─────────────────────────────────────────────────────────────

def main():
    try:
        while True:
            choice = main_menu()
            if choice is None or choice == "quit":
                clear()
                console.print("\n  Goodbye!\n")
                break
            elif choice == "reg": menu_register()
            elif choice == "test": menu_test()
            elif choice == "keys": menu_keys()
            elif choice == "export": menu_export()
            elif choice == "inject": menu_inject()
            elif choice == "status": menu_status()
            elif choice == "validate": menu_validate()
    except KeyboardInterrupt:
        clear()
        console.print("\n  Goodbye!\n")

if __name__ == "__main__":
    main()
