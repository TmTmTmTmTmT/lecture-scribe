"""프로세스 우선순위·메모리 관리 (macOS).

실측 근거(Apple M1 Pro 16GB, large-v3 int8):

| 항목 | 값 |
|---|---|
| 모델 상주 | large-v3 2,412MB / large-v3-turbo 1,401MB |
| 모델 해제 시 반환 | 1,620MB (large-v3) |
| 전사 1건 최고치 | 약 5.5GB(일시적), 상시는 2.6GB |
| 동시 2건 최고치 | 7.7GB — 여유 없으면 스왑 +2.2GB |
| 워커 스레드 QoS 기본값 | DEFAULT (메인 스레드는 USER_INTERACTIVE) |

QoS를 USER_INITIATED로 올려도 부하 상황 측정에서 이득은 오차 범위였다
(±4%). 그래도 의미상 맞는 등급이고 저전력·발열 상황에서 효율 코어로 강등되는
것을 막아 주므로 워커 스레드에 지정한다.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import gc
import os
import re
import subprocess
import sys
import threading
from typing import Final

from .logsetup import get_logger

logger = get_logger(__name__)

#: macOS QoS 클래스 상수 (sys/qos.h)
QOS_CLASS_USER_INTERACTIVE: Final[int] = 0x21
QOS_CLASS_USER_INITIATED: Final[int] = 0x19
QOS_CLASS_DEFAULT: Final[int] = 0x15
QOS_CLASS_UTILITY: Final[int] = 0x11
QOS_CLASS_BACKGROUND: Final[int] = 0x09

_QOS_NAMES: Final[dict[int, str]] = {
    QOS_CLASS_USER_INTERACTIVE: "USER_INTERACTIVE",
    QOS_CLASS_USER_INITIATED: "USER_INITIATED",
    QOS_CLASS_DEFAULT: "DEFAULT",
    QOS_CLASS_UTILITY: "UTILITY",
    QOS_CLASS_BACKGROUND: "BACKGROUND",
}


def _libsystem() -> ctypes.CDLL | None:
    try:
        name = ctypes.util.find_library("System") or "libSystem.B.dylib"
        lib = ctypes.CDLL(name)
    except OSError:  # pragma: no cover - macOS 외 플랫폼
        return None
    return lib


_LIB: Final[ctypes.CDLL | None] = _libsystem()


def set_thread_qos(qos_class: int = QOS_CLASS_USER_INITIATED) -> bool:
    """현재 스레드의 QoS 등급을 지정한다.

    워커 스레드는 기본이 DEFAULT라 저전력·발열 상황에서 효율 코어로 내려갈 수 있다.
    사용자가 결과를 기다리는 작업이므로 USER_INITIATED가 맞다.
    """
    if _LIB is None or not hasattr(_LIB, "pthread_set_qos_class_self_np"):
        return False
    func = _LIB.pthread_set_qos_class_self_np
    func.argtypes = [ctypes.c_uint, ctypes.c_int]
    func.restype = ctypes.c_int
    return bool(func(qos_class, 0) == 0)


def thread_qos() -> str:
    """현재 스레드의 QoS 등급 이름(진단용)."""
    if _LIB is None or not hasattr(_LIB, "pthread_get_qos_class_np"):
        return "unknown"
    _LIB.pthread_self.restype = ctypes.c_void_p
    getter = _LIB.pthread_get_qos_class_np
    getter.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint),
        ctypes.POINTER(ctypes.c_int),
    ]
    qos, relative = ctypes.c_uint(), ctypes.c_int()
    if getter(_LIB.pthread_self(), ctypes.byref(qos), ctypes.byref(relative)) != 0:
        return "unknown"
    return _QOS_NAMES.get(qos.value, hex(qos.value))


#: TransformProcessType 상수 (ApplicationServices/ProcessApplicationTransformState)
_K_CURRENT_PROCESS: Final[int] = 2
_K_TRANSFORM_TO_UI_ELEMENT: Final[int] = 4
_K_TRANSFORM_TO_FOREGROUND: Final[int] = 1


def hide_from_dock() -> bool:
    """이 프로세스를 Dock·앱 전환기에서 감춘다(UIElement로 전환)."""
    return _transform_process(_K_TRANSFORM_TO_UI_ELEMENT)


def show_in_dock() -> bool:
    """이 프로세스를 Dock에 보이는 정식 앱으로 승격한다.

    번들 Info.plist는 `LSUIElement=1`(Dock에 안 뜸)로 두고, **창을 띄우는 GUI
    프로세스만** 이 함수로 승격한다. 그래야 파이썬이 내부적으로 다시 실행하는
    보조 프로세스(`multiprocessing.resource_tracker` 등)까지 아이콘이 생기는
    문제를 막을 수 있다(실측: 전사 중 Dock 아이콘이 2개로 보이던 원인).
    """
    return _transform_process(_K_TRANSFORM_TO_FOREGROUND)


def _transform_process(transform: int) -> bool:
    try:
        services = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
    except OSError:  # pragma: no cover - macOS 외 플랫폼
        return False
    if not hasattr(services, "TransformProcessType"):  # pragma: no cover
        return False

    class ProcessSerialNumber(ctypes.Structure):
        _fields_ = [("highLongOfPSN", ctypes.c_uint32), ("lowLongOfPSN", ctypes.c_uint32)]

    psn = ProcessSerialNumber(0, _K_CURRENT_PROCESS)
    services.TransformProcessType.argtypes = [
        ctypes.POINTER(ProcessSerialNumber),
        ctypes.c_uint32,
    ]
    services.TransformProcessType.restype = ctypes.c_int
    result = services.TransformProcessType(ctypes.byref(psn), transform)
    if result != 0:
        logger.debug("TransformProcessType(%d) 실패: %d", transform, result)
    return bool(result == 0)


def _gc_collect_is_safe() -> bool:
    """지금 스레드에서 `gc.collect()`를 돌려도 안전한지(FIX_GUIDE_14 T-01).

    PySide6에서 부모 없는 QObject/QWidget이 순환 참조 쓰레기가 되면, `gc.collect()`를
    부른 **그 스레드에서** C++ 소멸자가 돈다. GUI 객체를 메인 스레드 밖에서 소멸시키는
    것은 Qt에서 정의되지 않은 동작이라 크래시 위험이 있다(테스트에서 실제로 재현된
    적 있음). 이 모듈은 GUI 비의존을 유지해야 하므로 Qt를 import하지 않고, 대신
    ① 메인 스레드면 항상 안전하고, ② PySide6가 아예 로드되지 않은 프로세스(CLI)면
    Qt 객체 자체가 없어 안전하다고 판단한다.
    """
    if threading.current_thread() is threading.main_thread():
        return True
    return "PySide6" not in sys.modules


def release_memory() -> float:
    """해제된 힙 페이지를 OS에 돌려준다. 돌려준 양(MB)을 대략 보고한다.

    파이썬 GC만으로는 malloc이 잡아 둔 페이지가 OS로 돌아가지 않는다.
    긴 전사 뒤에 호출하면 스왑 압력을 줄일 수 있다.

    GUI 워커 스레드에서는 `gc.collect()`를 건너뛴다(`_gc_collect_is_safe` 참고) —
    `malloc_zone_pressure_relief`는 스레드와 무관하게 그대로 호출해 이미 참조계수로
    해제된 페이지는 정상 반환한다. 건너뛴 몫은 GUI가 파일 완료 시 메인 스레드에서
    한 번 더 호출해 보전한다(`gui/window.py _on_job_done`).
    """
    if _gc_collect_is_safe():
        gc.collect()
    if _LIB is None or not hasattr(_LIB, "malloc_zone_pressure_relief"):
        return 0.0
    func = _LIB.malloc_zone_pressure_relief
    func.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    func.restype = ctypes.c_size_t
    return float(func(None, 0)) / 1024 / 1024


def process_rss_mb() -> float:
    """현재 프로세스의 물리 메모리 사용량(MB)."""
    try:
        out = subprocess.run(
            ["/bin/ps", "-o", "rss=", "-p", str(os.getpid())],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):  # pragma: no cover
        return 0.0
    return int(out) / 1024 if out.isdigit() else 0.0


def available_memory_gb() -> float:
    """지금 실제로 쓸 수 있는 물리 메모리(GB).

    전체 메모리가 아니라 **가용량**을 봐야 한다. 여유가 없는 상태에서 동시 전사를
    강행하면 스왑이 늘면서 전체 처리량이 절반 이하로 떨어진다(실측).
    """
    try:
        out = subprocess.run(
            ["/usr/bin/vm_stat"], capture_output=True, text=True, timeout=5, check=False
        ).stdout
    except (OSError, subprocess.TimeoutExpired):  # pragma: no cover
        return 0.0
    page_size = 4096
    match = re.search(r"page size of (\d+) bytes", out)
    if match:
        page_size = int(match.group(1))
    counts: dict[str, int] = {}
    for line in out.splitlines():
        entry = re.match(r'"?([^":]+)"?:\s+(\d+)', line.strip())
        if entry:
            counts[entry.group(1).strip()] = int(entry.group(2))
    pages = (
        counts.get("Pages free", 0)
        + counts.get("Pages inactive", 0)
        + counts.get("Pages speculative", 0)
        + counts.get("Pages purgeable", 0)
    )
    return pages * page_size / 1024**3


def swap_used_mb() -> float:
    """현재 스왑 사용량(MB). 진단·경고용."""
    try:
        out = subprocess.run(
            ["/usr/sbin/sysctl", "-n", "vm.swapusage"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):  # pragma: no cover
        return 0.0
    match = re.search(r"used\s*=\s*([\d.]+)M", out)
    return float(match.group(1)) if match else 0.0


#: 모델별 실측 상주 메모리(GB). 저메모리 경고와 동시 실행 계산에 쓴다.
MODEL_MEMORY_GB: Final[dict[str, float]] = {
    "large-v3-turbo": 1.4,
    "large-v3": 2.4,
    "medium": 1.0,
    "small": 0.6,
    "base": 0.3,
    "tiny": 0.2,
}


def model_memory_gb(model_name: str) -> float:
    for key, value in MODEL_MEMORY_GB.items():
        if model_name.startswith(key):
            return value
    return 2.4


#: UI 스레드와 시스템 몫으로 남겨 둘 코어 수.
#: 실측: cpu_threads=0(전체 10코어) × num_workers=2 로 돌리면 10코어에 스레드 20개가
#: 몰려 UI 스레드가 기아 상태가 되고 창이 "응답 없음"으로 멈춘다.
_RESERVED_CORES: Final[int] = 2


def usable_cpu_threads(requested: int = 0, parallel: int = 1) -> int:
    """전사 1건에 배정할 CPU 스레드 수.

    `requested`가 0이면 자동: (전체 코어 - 예약분)을 동시 전사 수로 나눈다.
    전체 코어를 그대로 쓰면 UI 스레드가 밀려 창이 멈춘다(실측).
    """
    cores = os.cpu_count() or 4
    if requested > 0:
        return max(1, min(requested, cores))
    budget = max(1, cores - _RESERVED_CORES)
    return max(1, budget // max(1, parallel))


# --- mlx (Metal GPU) 메모리 ---------------------------------------------------
#
# mlx-whisper 0.4.3은 `mlx_whisper.transcribe.ModelHolder`라는 **프로세스 전역 클래스
# 변수**에 모델을 캐시한다(실측: 소스 확인):
#
#     class ModelHolder:
#         model = None
#         @classmethod
#         def get_model(cls, model_path, dtype):
#             if cls.model is None or model_path != cls.model_path:
#                 cls.model = load_model(model_path, dtype=dtype)
#
# 락이 없다. 스레드 두 개가 동시에 들어오면 둘 다 `cls.model is None`을 보고 **각자
# 모델 전체를 로드**해 메모리를 두 배로 쓴다 → 여유가 없으면 둘 다 OOM으로 죽는다.
# 해제 수단도 없어서 실패해도 메모리가 그대로 남는다.
# 그래서 로드는 직렬화하고(backends/mlx.py의 락), 해제는 아래에서 직접 한다.


def _mlx_core() -> object | None:
    try:
        import mlx.core as mx
    except ImportError:
        return None
    return mx


def mlx_active_memory_gb() -> float:
    """mlx가 현재 잡고 있는 GPU 메모리(GB). mlx가 없으면 0."""
    mx = _mlx_core()
    if mx is None:
        return 0.0
    try:
        return float(mx.get_active_memory()) / 1024**3  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - 진단용, 실패해도 진행
        return 0.0


def mlx_cache_memory_gb() -> float:
    """mlx 버퍼 캐시 크기(GB). 해제 대상."""
    mx = _mlx_core()
    if mx is None:
        return 0.0
    try:
        return float(mx.get_cache_memory()) / 1024**3  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return 0.0


def mlx_release_model() -> float:
    """mlx 전역 모델 캐시와 버퍼 캐시를 비운다. 반환한 메모리(GB).

    `MlxWhisperBackend.unload()`가 자기 필드만 지워서는 아무것도 반환되지 않는다.
    실제로 잡고 있는 것은 `ModelHolder.model`과 mlx 내부 버퍼 캐시다.
    """
    mx = _mlx_core()
    if mx is None:
        return 0.0
    before = mlx_active_memory_gb() + mlx_cache_memory_gb()
    try:
        import importlib

        holder = importlib.import_module("mlx_whisper.transcribe").ModelHolder
        holder.model = None
        holder.model_path = None
    except (ImportError, AttributeError) as exc:  # pragma: no cover - 설치본 구조 변경
        logger.debug("mlx ModelHolder 해제 건너뜀: %s", exc)
    if _gc_collect_is_safe():  # FIX_GUIDE_14 T-01
        gc.collect()
    try:
        mx.clear_cache()  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        logger.debug("mx.clear_cache 실패: %s", exc)
    freed = before - (mlx_active_memory_gb() + mlx_cache_memory_gb())
    if freed > 0.05:
        logger.info("mlx 메모리 %.2fGB 반환", freed)
    return max(0.0, freed)


def mlx_limit_cache(limit_gb: float = 1.5) -> None:
    """mlx 버퍼 캐시 상한을 걸어 무한 증가를 막는다."""
    mx = _mlx_core()
    if mx is None:
        return
    try:
        mx.set_cache_limit(int(limit_gb * 1024**3))  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        logger.debug("mx.set_cache_limit 실패: %s", exc)


def check_memory_headroom(model_name: str) -> str | None:
    """메모리가 빠듯하면 사용자에게 보여줄 안내 문구를 돌려준다."""
    available = available_memory_gb()
    if available <= 0:
        return None
    needed = model_memory_gb(model_name) + 2.0  # 모델 + 전사 작업 공간
    if available >= needed:
        return None
    lighter = "large-v3-turbo" if not model_name.startswith("large-v3-turbo") else "medium"
    return (
        f"가용 메모리가 {available:.1f}GB 뿐입니다(이 모델에 약 {needed:.1f}GB 필요). "
        f"스왑이 늘어 느려질 수 있습니다. 다른 앱을 닫거나 더 가벼운 모델"
        f"({lighter})을 쓰는 것을 권합니다."
    )
