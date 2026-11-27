"""Read-only Windows furnace telemetry. No CUDA context, torch, or subprocess."""
import ctypes
import os
import threading
import time
from pathlib import Path


class _Memory(ctypes.Structure):
    _fields_ = [(k, ctypes.c_ulonglong) for k in ('total', 'free', 'used')]


class _Util(ctypes.Structure):
    _fields_ = [('gpu', ctypes.c_uint), ('memory', ctypes.c_uint)]


class _Ram(ctypes.Structure):
    _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
        (k, ctypes.c_ulonglong) for k in ('total', 'available', 'page_total',
                                          'page_available', 'virtual_total',
                                          'virtual_available', 'extended_available')]


def _ram():
    value = _Ram()
    value.length = ctypes.sizeof(value)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
        return value.total - value.available, value.total
    return None, None


class NvmlReader:
    def __init__(self):
        paths = [
            Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'nvml.dll',
            Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'NVIDIA Corporation' / 'NVSMI' / 'nvml.dll',
        ]
        self.lib = None
        for path in paths:
            try:
                self.lib = ctypes.CDLL(str(path))
                break
            except OSError:
                pass
        if self.lib is None:
            raise OSError('找不到 NVIDIA NVML')
        self._call('nvmlInit_v2', [], [])
        self.handle = ctypes.c_void_p()
        try:
            self._call('nvmlDeviceGetHandleByIndex_v2',
                       [ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)],
                       [0, ctypes.byref(self.handle)])
        except Exception:
            self.close()
            raise
        name = ctypes.create_string_buffer(96)
        self.name = 'NVIDIA GPU 0'
        try:
            self._call('nvmlDeviceGetName', [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint],
                       [self.handle, name, len(name)])
            self.name = name.value.decode('utf-8', errors='replace')
        except (OSError, AttributeError):
            pass

    def _call(self, name, types, args):
        fn = getattr(self.lib, name)
        fn.argtypes = types
        fn.restype = ctypes.c_int
        rc = fn(*args)
        if rc:
            raise OSError(f'NVML {name}: {rc}')

    def _read(self, name, value, *extra):
        try:
            self._call(name, [ctypes.c_void_p] + [ctypes.c_uint] * len(extra)
                       + [ctypes.POINTER(type(value))],
                       [self.handle, *extra, ctypes.byref(value)])
            return value
        except (OSError, AttributeError):
            return None

    def sample(self):
        temp = self._read('nvmlDeviceGetTemperature', ctypes.c_uint(), 0)
        watts = self._read('nvmlDeviceGetPowerUsage', ctypes.c_uint())
        limit = self._read('nvmlDeviceGetPowerManagementLimit', ctypes.c_uint())
        util = self._read('nvmlDeviceGetUtilizationRates', _Util())
        mem = self._read('nvmlDeviceGetMemoryInfo', _Memory())
        ram_used, ram_total = _ram()
        if all(x is None for x in (temp, watts, util, mem)):
            raise OSError('NVML 未回傳 GPU 資料')
        return dict(name=self.name, temperature=temp.value if temp is not None else None,
                    power_w=watts.value / 1000 if watts is not None else None,
                    power_limit_w=limit.value / 1000 if limit is not None else None,
                    gpu_percent=util.gpu if util is not None else None,
                    memory_percent=util.memory if util is not None else None,
                    vram_used=mem.used if mem is not None else None,
                    vram_total=mem.total if mem is not None else None,
                    ram_used=ram_used, ram_total=ram_total)

    def close(self):
        try:
            self._call('nvmlShutdown', [], [])
        except (OSError, AttributeError):
            pass


class FireWatch:
    """Advisory only. Require sustained low power AND no sampling progress."""
    def __init__(self):
        self.key = None
        self.since = None
        self.last = None

    def check(self, data, state, now):
        low = (state is not None and data.get('gpu_percent') is not None
               and data['gpu_percent'] >= 95 and data.get('power_w') is not None
               and data['power_w'] < 65)
        if not low:
            self.key = self.since = self.last = None
            return False
        key, last_progress, _phase = state
        if key != self.key or self.last is None or now - self.last > 8:
            self.key, self.since = key, now
        self.last = now
        return now - self.since >= 90 and now - last_progress >= 90


class FireMonitor:
    """One daemon samples at 3s; HTTP handlers only read a shared cache."""
    def __init__(self, sampling_state, reader_factory=NvmlReader, clock=time.monotonic):
        self.sampling_state = sampling_state
        self.reader_factory = reader_factory
        self.clock = clock
        self.lock = threading.Lock()
        self.started = False
        self.data = {'available': False, 'reason': '正在請示丹火'}
        self.updated = None

    def snapshot(self):
        with self.lock:
            if not self.started:
                self.started = True
                threading.Thread(target=self._run, daemon=True, name='dan-fire-monitor').start()
            if self.updated is not None and self.clock() - self.updated > 10:
                return {'available': False, 'reason': '丹火儀訊號逾時'}
            return dict(self.data)

    def _publish(self, data):
        with self.lock:
            self.data, self.updated = data, self.clock()

    def _run(self):
        reader = None
        watch = FireWatch()
        while True:
            try:
                if reader is None:
                    reader = self.reader_factory()
                data = reader.sample()
                state = self.sampling_state()
                now = self.clock()
                warning = watch.check(data, state, now)
                self._publish(dict(data, available=True, sampling=state is not None,
                                   phase=state[2] if state else None, warning=warning))
                time.sleep(3)
            except Exception as error:
                watch = FireWatch()
                self._publish({'available': False, 'reason': str(error)[:160]})
                if reader is not None:
                    try:
                        reader.close()
                    except Exception:
                        pass
                    reader = None
                time.sleep(3)
