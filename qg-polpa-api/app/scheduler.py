import threading
import time
from datetime import datetime, timedelta

from app.database import criar_forecast_snapshot, get_snapshot_datas, notificar_tarefas_vencidas

# Quarta-feira às 08h30 (datetime.weekday(): Segunda=0 ... Quarta=2)
TARGET_WEEKDAY = 2
TARGET_HOUR = 14
TARGET_MINUTE = 30


def _next_run(now: datetime) -> datetime:
    candidate = now.replace(hour=TARGET_HOUR, minute=TARGET_MINUTE, second=0, microsecond=0)
    days_ahead = (TARGET_WEEKDAY - now.weekday()) % 7
    candidate += timedelta(days=days_ahead)
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate


def _ja_existe_snapshot_hoje() -> bool:
    hoje = datetime.now().strftime("%Y-%m-%d")
    try:
        datas = get_snapshot_datas()
    except Exception:
        return False
    return any(d.get("snapshotDate") == hoje for d in datas)


def _loop() -> None:
    while True:
        agora = datetime.now()
        proximo = _next_run(agora)
        segundos = max(1.0, (proximo - agora).total_seconds())
        time.sleep(segundos)
        try:
            if not _ja_existe_snapshot_hoje():
                criar_forecast_snapshot()
        except Exception as exc:
            print(f"[scheduler] Falha ao criar snapshot semanal: {exc}")


def iniciar_scheduler_snapshot_semanal() -> None:
    """Inicia uma thread em segundo plano que congela o forecast toda quarta-feira às 14h30."""
    thread = threading.Thread(target=_loop, daemon=True, name="snapshot-semanal-scheduler")
    thread.start()


# Independente do scheduler de snapshot acima — checa tarefas vencidas a cada 6h
# (roda uma vez logo na subida do processo, sem esperar o primeiro intervalo).
INTERVALO_CHECAGEM_VENCIDAS_SEGUNDOS = 6 * 60 * 60


def _loop_tarefas_vencidas() -> None:
    while True:
        try:
            notificar_tarefas_vencidas()
        except Exception as exc:
            print(f"[scheduler] Falha ao notificar tarefas vencidas: {exc}")
        time.sleep(INTERVALO_CHECAGEM_VENCIDAS_SEGUNDOS)


def iniciar_scheduler_tarefas_vencidas() -> None:
    """Inicia uma thread em segundo plano que notifica o responsável quando uma
    tarefa passa do prazo sem ser concluída."""
    thread = threading.Thread(target=_loop_tarefas_vencidas, daemon=True, name="tarefas-vencidas-scheduler")
    thread.start()
