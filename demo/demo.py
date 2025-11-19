import os
import time
import random
import threading
from concurrent.futures import ThreadPoolExecutor

# ------------------------------------------------------------------
# 1. Force safe Matplotlib backend (eliminates all GUI/thread warnings)
# ------------------------------------------------------------------
import matplotlib
matplotlib.use('Agg')          # <-- Critical line! Safe in threads
import matplotlib.pyplot as plt

from calc_notifier import Notifier

# Two independent notifiers
calc_a = Notifier(name="Task A", track_uptime=True, debug=True)
calc_b = Notifier(name="Task B", track_uptime=True, debug=True)


# ------------------------------------------------------------------
# 3. Decorated calculation steps
# ------------------------------------------------------------------
@calc_a.catch_exceptions(context="task A", reraise=True)
def step_a(iteration: int):
    print(f"[A] Starting iteration {iteration}...")
    time.sleep(1.5 + random.random())

    # Normal plot
    x = range(50)
    y = [random.gauss(100 + iteration * 0.5, 8) for _ in x]

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(x, y, label=f"Iter {iteration}", linewidth=2)
    ax.set_title(f"Backtest 2025-Q4 – Iteration {iteration}")
    ax.legend()
    ax.grid(True, alpha=0.3)

    calc_a.report(
        title=f"Intermediate Result #{iteration}",
        text=f"Mean value: {sum(y)/len(y):.3f}\n"
             f"Std dev: {random.uniform(0.5, 3):.3f}\n"
             f"Status: Running smoothly",
        figures=[fig],
        send=True
    )

    # Simulate user crash on iteration 6
    if iteration == 6:
        raise ZeroDivisionError("Simulated calculation crash (user error)")

    # Try to create plot in background thread (will trigger MatplotlibThreadSafetyError)
    if iteration == 8:
        def bad_thread_plot():
            print("   [A] Creating figure in background thread (should be blocked)...")
            fig2, ax2 = plt.subplots(figsize=(7, 4))
            ax2.plot([1, 2, 3, 4], [1, 9, 2, 8], 'r-o')
            ax2.set_title("Figure created in thread – will be skipped")
            calc_a.report(
                title="Thread-safety test",
                text="This figure should NOT appear (created in background thread)",
                figures=[fig2],
                send=True
            )
            plt.close(fig2)

        threading.Thread(target=bad_thread_plot, daemon=True).start()
        time.sleep(1)  # give thread time to trigger the error


@calc_b.catch_exceptions(context="validation phase", reraise=True)
def step_b(iteration: int):
    time.sleep(2.2)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    ax1.plot([0, 1, 2, 3], [0, 1, 4, 2], 'go-')
    ax1.set_title("Profit curve")
    ax2.bar(["Win", "Loss", "Draw"], [65, 25, 10], color=['green', 'red', 'gray'])
    ax2.set_title("Trade outcome distribution")

    calc_b.report(
        title=f"Validation Step {iteration}/10",
        text=f"Sharpe ratio: {random.uniform(0.8, 2.7):.2f}\n"
             f"Max drawdown: {random.uniform(5, 25):.1f}%",
        figures=[fig],
        send=True
    )
    plt.close(fig)


# ------------------------------------------------------------------
# 4. Run both calculations in parallel
# ------------------------------------------------------------------
print("Launching two independent calculations in parallel...\n")

with ThreadPoolExecutor(max_workers=2) as pool:
    # First steps immediately
    pool.submit(step_a, 1)
    pool.submit(step_b, 1)

    # Remaining iterations with small delays
    for i in range(2, 11):
        time.sleep(4.5)
        if i <= 9:
            pool.submit(step_a, i)
        if i <= 10:
            pool.submit(step_b, i)

print("\nAll iterations completed!")
print(f"History folders:")
print(f"   A → {calc_a.history_dir}")
print(f"   B → {calc_b.history_dir}")
print("\nCheck your Telegram chat – you should see:")
print("   • Regular reports with plots & PDF")
print("   • One full-traceback error (iteration 6)")
print("   • One friendly Matplotlib thread-safety warning (iteration 8)")
print("   • Uptime counter on every message")