"""Демонстрация использования calc_notifier.

Запуск:
- отредактируй config.example.json -> config.json (в корне проекта)
- установи зависимости: pip install -r requirements.txt
- запусти: python demo.py
- открой Grafana/Prometheus (если настроены) или смотри Telegram (если включён)
"""
import time
import math
import random
import json
import os
import matplotlib.pyplot as plt

from calc_notifier import Notifier

# ищем config
conf_path = 'config.json' if os.path.exists('config.json') else 'config.example.json'
notifier = Notifier(conf_path)

# запустим prometheus server
notifier.start_metrics_server()

N = 300
data = []
for i in range(N):
    # имитация тяжёлого расчёта
    x = i
    y = math.sin(i / 20.0) + random.random() * 0.1
    data.append(y)

    # логируем метрики
    notifier.log_metric('calc_iteration', i)
    notifier.log_metric('calc_value', y)

    # раз в default_interval отправляем отчёт
    interval = notifier.config['report'].get('default_interval', 100)
    if i % interval == 0 and i > 0:
        fig, ax = plt.subplots()
        ax.plot(range(len(data)), data)
        ax.set_title(f"Status at iter {i}")
        ax.grid(True)
        notifier.report(f"Iteration {i}", figure=fig, extra_info={'iteration': i, 'value': float(y)})
        plt.close(fig)

    time.sleep(1)


# демонстрируем report_exception
try:
raise RuntimeError('Demo error')
except Exception as e:
notifier.report_exception(e, context='during demo run')


print("Demo finished. History dir:", notifier.history_dir)