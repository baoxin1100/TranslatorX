from __future__ import annotations

import ctypes
import logging
import threading
import time

import numpy as np

from . import _wgc_d3d11 as d3d11
from ._wgc_rotypes import IInspectable
from ._wgc_rotypes.Windows.Foundation import TypedEventHandler
from ._wgc_rotypes.Windows.Graphics.Capture import (
    Direct3D11CaptureFramePool,
    GraphicsCaptureItem,
    IGraphicsCaptureItem,
    IGraphicsCaptureItemInterop,
)
from ._wgc_rotypes.Windows.Graphics.DirectX import DirectXPixelFormat
from ._wgc_rotypes.Windows.Graphics.DirectX.Direct3D11 import (
    CreateDirect3D11DeviceFromDXGIDevice,
    IDirect3DDevice,
    IDirect3DDxgiInterfaceAccess,
)
from ._wgc_rotypes.roapi import GetActivationFactory
from .models import WindowInfo


_PBYTE = ctypes.POINTER(ctypes.c_ubyte)
_FRAME_TIMEOUT_SECONDS = 2.0


class WgcCapture:
    """Minimal HWND Windows Graphics Capture implementation."""

    def __init__(self) -> None:
        self._logger = logging.getLogger("translatorx.wgc")
        self._lock = threading.RLock()
        self._frame_lock = threading.Lock()
        self._frame_event = threading.Event()
        self._frame_requested = False
        self._last_frame = None
        self._hwnd = 0
        self._frame_pool = None
        self._session = None
        self._item = None
        self._runtime_device = None
        self._device = None
        self._context = None
        self._cpu_texture = None
        self._last_size = None
        self._closed_delegate = None
        self._frame_delegate = None
        self._active_logged = False
        self._retry_after = 0.0

    def _start(self, window: WindowInfo) -> bool:
        if self._frame_pool is not None and self._hwnd == int(window.hwnd):
            return True
        self.close()
        if time.monotonic() < self._retry_after:
            return False
        if not ctypes.windll.user32.IsWindow(int(window.hwnd)):
            return False
        try:
            interop = GetActivationFactory(
                "Windows.Graphics.Capture.GraphicsCaptureItem"
            ).astype(IGraphicsCaptureItemInterop)
            self._device = d3d11.ID3D11Device()
            self._context = d3d11.ID3D11DeviceContext()
            d3d11.D3D11CreateDevice(
                None, d3d11.D3D_DRIVER_TYPE_HARDWARE, None,
                d3d11.D3D11_CREATE_DEVICE_BGRA_SUPPORT,
                None, 0, d3d11.D3D11_SDK_VERSION,
                ctypes.byref(self._device), None, ctypes.byref(self._context),
            )
            self._runtime_device = CreateDirect3D11DeviceFromDXGIDevice(self._device)
            self._item = interop.CreateForWindow(int(window.hwnd), IGraphicsCaptureItem.GUID)
            self._last_size = self._item.Size
            self._frame_pool = Direct3D11CaptureFramePool.CreateFreeThreaded(
                self._runtime_device, DirectXPixelFormat.B8G8R8A8UIntNormalized,
                2, self._last_size,
            )
            self._session = self._frame_pool.CreateCaptureSession(self._item)
            self._closed_delegate = TypedEventHandler(
                GraphicsCaptureItem, IInspectable
            ).delegate(lambda *_: self.close())
            self._item.add_Closed(self._closed_delegate)
            self._frame_delegate = TypedEventHandler(
                Direct3D11CaptureFramePool, IInspectable
            ).delegate(self._on_frame_arrived)
            self._frame_pool.add_FrameArrived(self._frame_delegate)
            self._session.IsCursorCaptureEnabled = False
            try:
                self._session.IsBorderRequired = False
            except Exception:
                pass
            self._hwnd = int(window.hwnd)
            self._session.StartCapture()
            return True
        except Exception:
            self._logger.exception("WGC 初始化失败")
            self.close()
            self._retry_after = time.monotonic() + 5.0
            return False

    def _on_frame_arrived(self, *_args) -> None:
        native_frame = None
        try:
            with self._lock:
                if self._frame_pool is None:
                    return
                native_frame = self._frame_pool.TryGetNextFrame()
                if native_frame is None or not self._frame_requested:
                    return
                frame = self._copy_frame(native_frame)
                if frame is not None:
                    self._last_frame = frame
                    self._frame_requested = False
                    self._frame_event.set()
        except Exception:
            self._logger.exception("WGC 帧读取失败")
        finally:
            if native_frame is not None and hasattr(native_frame, "Close"):
                native_frame.Close()

    def _copy_frame(self, frame):
        size = frame.ContentSize
        if size.Width != self._last_size.Width or size.Height != self._last_size.Height:
            self._last_size = size
            self._release_cpu_texture()
            self._frame_pool.Recreate(
                self._runtime_device, DirectXPixelFormat.B8G8R8A8UIntNormalized,
                2, size,
            )
            return None
        texture = None
        mapped = False
        try:
            texture = frame.Surface.astype(IDirect3DDxgiInterfaceAccess).GetInterface(
                d3d11.ID3D11Texture2D.GUID
            ).astype(d3d11.ID3D11Texture2D)
            if self._cpu_texture is None:
                description = texture.GetDesc()
                description.Usage = d3d11.D3D11_USAGE_STAGING
                description.CPUAccessFlags = d3d11.D3D11_CPU_ACCESS_READ
                description.BindFlags = 0
                description.MiscFlags = 0
                self._cpu_texture = self._device.CreateTexture2D(
                    ctypes.byref(description), None
                )
            self._context.CopyResource(self._cpu_texture, texture)
            mapped_info = self._context.Map(
                self._cpu_texture, 0, d3d11.D3D11_MAP_READ, 0
            )
            mapped = True
            bgra = np.ctypeslib.as_array(
                ctypes.cast(mapped_info.pData, _PBYTE),
                (size.Height, mapped_info.RowPitch // 4, 4),
            )[:, :size.Width].copy()
            # Dropping alpha creates a strided view. Return an owned,
            # C-contiguous BGR array so capture validation and OpenCV consumers
            # receive the format promised by this backend.
            return bgra[:, :, :3].copy()
        finally:
            if mapped:
                self._context.Unmap(self._cpu_texture, 0)
            if texture is not None:
                texture.Release()

    def get_frame(self, window: WindowInfo):
        with self._frame_lock:
            if not self._start(window):
                return None
            with self._lock:
                self._last_frame = None
                self._frame_event.clear()
                self._frame_requested = True
            if not self._frame_event.wait(_FRAME_TIMEOUT_SECONDS):
                with self._lock:
                    self._frame_requested = False
                self._logger.warning("WGC 在 %.1f 秒内未返回帧", _FRAME_TIMEOUT_SECONDS)
                return None
            with self._lock:
                frame = self._last_frame
                self._last_frame = None
            if frame is None:
                return None
            frame = self._crop_to_client(frame, window.width, window.height)
            if frame is not None and frame.size and not self._active_logged:
                self._logger.info(
                    "WGC 已返回有效帧：hwnd=%s shape=%s", window.hwnd, frame.shape
                )
                self._active_logged = True
            return frame

    @staticmethod
    def _crop_to_client(frame, client_width: int, client_height: int):
        frame_height, frame_width = frame.shape[:2]
        if frame_width == client_width and frame_height == client_height:
            return frame
        border = round((frame_width - client_width) / 2)
        title_height = frame_height - client_height - border
        if border < 0 or title_height < 0:
            return None
        cropped = frame[title_height:frame_height - border, border:frame_width - border]
        return cropped.copy() if cropped.shape[:2] == (client_height, client_width) else None

    def _release_cpu_texture(self) -> None:
        if self._cpu_texture is not None:
            self._cpu_texture.Release()
            self._cpu_texture = None

    def close(self) -> None:
        with self._lock:
            self._frame_requested = False
            self._frame_event.set()
            self._release_cpu_texture()
            for attribute in ("_frame_pool", "_session"):
                resource = getattr(self, attribute)
                if resource is not None:
                    try:
                        resource.Close()
                    except Exception:
                        pass
                    setattr(self, attribute, None)
            self._item = None
            for attribute in ("_runtime_device", "_device", "_context"):
                resource = getattr(self, attribute)
                if resource is not None:
                    resource.Release()
                    setattr(self, attribute, None)
            self._closed_delegate = None
            self._frame_delegate = None
            self._last_frame = None
            self._last_size = None
            self._hwnd = 0
            self._active_logged = False


_CAPTURE = WgcCapture()


def capture_window_wgc(window: WindowInfo):
    return _CAPTURE.get_frame(window)


def close_wgc_capture() -> None:
    _CAPTURE.close()
