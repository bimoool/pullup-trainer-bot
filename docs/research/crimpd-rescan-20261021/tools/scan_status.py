"""usage: scan_status.py STATUS "last scenario" "current check" "next action" ["tool errors"]"""
import csv,sys,datetime,collections
D="docs/research/crimpd-rescan-20261021/"
rows=list(csv.reader(open(D+"coverage.csv",encoding="utf-8")))[1:]
c=collections.Counter(r[3] for r in rows)
obs=sum(1 for _ in open(D+"observations.csv",encoding="utf-8"))-1
st,last,cur,nxt=sys.argv[1:5]; err=sys.argv[5] if len(sys.argv)>5 else "ошибки не наблюдалось"
open(D+"scan-status.md","w",encoding="utf-8").write(f"""# scan-status
- Время: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} (локальное, Mac)
- Статус: {st}
- Последний законченный сценарий: {last}
- Текущая проверка: {cur}
- Следующее конкретное действие: {nxt}
- Покрытие ({len(rows)}): OBSERVED {c['OBSERVED']} · PARTIAL {c['PARTIAL']} · BLOCKED {c['BLOCKED']} · UNKNOWN {c['UNKNOWN']} · NOT_STARTED {c['NOT_STARTED']}
- Наблюдений: {obs}
- Ошибки инструментов: {err}
- Разбор остатков: coverage-triage.csv (по каждому PARTIAL/UNKNOWN)
- Эмулятор: source ~/android-ref-lab/env.sh; emulator -avd ref_pixel6_play -dns-server 8.8.8.8,1.1.1.1 -no-audio; хелперы ~/android-ref-lab/{{rs.sh,tt.sh,snap.sh}}
""")
