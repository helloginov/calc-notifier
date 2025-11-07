import os
import time
import math
import random
import matplotlib.pyplot as plt
from calc_notifier import Notifier

conf = "config.json"
notifier = Notifier(conf)

# simple loop that produces plots and reports every 50 iterations
N = 200
data = []
for i in range(N):
    val = math.sin(i / 20.0) + (random.random() - 0.5) * 0.2
    data.append(val)
    # log and at intervals create a figure and report
    if i % 50 == 0 and i > 0:
        fig, ax = plt.subplots()
        ax.plot(range(len(data)), data)
        ax.set_title(f"State at iter {i}")
        ax.grid(True)
        # send report: title, text, figures, extra files (optional)
        notifier.report(title=f"Iteration {i}", text=f"Iteration {i} report. Latest value = {val:.4f}",
                        figures=[fig], image_paths=None, files=None, send=True)
        plt.close(fig)
    time.sleep(0.5)

# example of saving artifacts without sending
folder = notifier.save_artifact(filename="test.txt", content=b"some cached results")
print("Saved artifact:", folder)
