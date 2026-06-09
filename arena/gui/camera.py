"""Camera controls for pan and zoom."""

from dataclasses import dataclass, field


# Per-frame blend factor for smooth panning (0→1).
# Higher = faster arrival.  0.12 gives a ~8-frame glide.
_PAN_LERP_SPEED: float = 0.12

# When the remaining distance (in world units) is below this
# threshold, snap to the target to avoid endless micro-drift.
_PAN_SNAP_THRESHOLD: float = 0.5

# Per-frame blend factor for smooth zoom transitions.
_ZOOM_LERP_SPEED: float = 0.10

# Snap threshold for zoom (proportional difference).
_ZOOM_SNAP_THRESHOLD: float = 0.005


@dataclass
class Camera:
    """Camera for panning and zooming the hex grid view."""

    x: float = 0.0  # World position
    y: float = 0.0
    zoom: float = 1.0
    min_zoom: float = 0.25
    max_zoom: float = 3.0

    # Smooth-pan target (None = no active glide)
    _target_x: float | None = field(default=None, repr=False)
    _target_y: float | None = field(default=None, repr=False)

    # Smooth-zoom target (None = no active zoom transition)
    _target_zoom: float | None = field(default=None, repr=False)

    def world_to_screen(self, world_x: float, world_y: float) -> tuple[int, int]:
        """Convert world coordinates to screen coordinates."""
        screen_x = (world_x - self.x) * self.zoom
        screen_y = (world_y - self.y) * self.zoom
        return (int(screen_x), int(screen_y))

    def screen_to_world(self, screen_x: int, screen_y: int) -> tuple[float, float]:
        """Convert screen coordinates to world coordinates."""
        world_x = screen_x / self.zoom + self.x
        world_y = screen_y / self.zoom + self.y
        return (world_x, world_y)

    def pan(self, dx: float, dy: float) -> None:
        """Pan the camera by a delta (cancels any smooth glide/zoom)."""
        self._target_x = None
        self._target_y = None
        self._target_zoom = None
        self.x -= dx / self.zoom
        self.y -= dy / self.zoom

    def center_on(
        self, world_x: float, world_y: float,
        viewport_width: int, viewport_height: int,
    ) -> None:
        """Center the camera on a world position (instant snap).

        Args:
            world_x: World X coordinate to center on.
            world_y: World Y coordinate to center on.
            viewport_width: Width of the viewport in screen pixels.
            viewport_height: Height of the viewport in screen pixels.
        """
        self._target_x = None
        self._target_y = None
        self.x = world_x - viewport_width / (2 * self.zoom)
        self.y = world_y - viewport_height / (2 * self.zoom)

    def smooth_center_on(
        self, world_x: float, world_y: float,
        viewport_width: int, viewport_height: int,
    ) -> None:
        """Begin a smooth glide to center the camera on a world position.

        Call :meth:`update` each frame to advance the animation.
        If the camera is already at the target, this is a no-op.

        Args:
            world_x: World X coordinate to center on.
            world_y: World Y coordinate to center on.
            viewport_width: Width of the viewport in screen pixels.
            viewport_height: Height of the viewport in screen pixels.
        """
        # Use the target zoom if a zoom transition is in progress,
        # so the pan target matches where we'll end up.
        z = self._target_zoom if self._target_zoom is not None else self.zoom
        self._target_x = world_x - viewport_width / (2 * z)
        self._target_y = world_y - viewport_height / (2 * z)

    def smooth_frame_on(
        self, world_x: float, world_y: float,
        target_zoom: float,
        viewport_width: int, viewport_height: int,
    ) -> None:
        """Begin a smooth glide + zoom to frame a world position.

        Combines :meth:`smooth_center_on` with a smooth zoom transition
        so the camera simultaneously pans and zooms to the desired view.

        Args:
            world_x: World X coordinate to center on.
            world_y: World Y coordinate to center on.
            target_zoom: Desired zoom level at the end of the transition.
            viewport_width: Width of the viewport in screen pixels.
            viewport_height: Height of the viewport in screen pixels.
        """
        target_zoom = max(self.min_zoom, min(self.max_zoom, target_zoom))
        self._target_zoom = target_zoom
        # Compute pan target using the destination zoom level
        self._target_x = world_x - viewport_width / (2 * target_zoom)
        self._target_y = world_y - viewport_height / (2 * target_zoom)

    def update(self) -> None:
        """Advance smooth-pan and smooth-zoom interpolation by one frame.

        Call once per frame.  Does nothing if no smooth transitions are active.
        """
        # --- Smooth zoom ---
        if self._target_zoom is not None:
            dz = self._target_zoom - self.zoom
            if abs(dz) < _ZOOM_SNAP_THRESHOLD:
                self.zoom = self._target_zoom
                self._target_zoom = None
            else:
                self.zoom += dz * _ZOOM_LERP_SPEED

        # --- Smooth pan ---
        if self._target_x is None or self._target_y is None:
            return

        dx = self._target_x - self.x
        dy = self._target_y - self.y

        if abs(dx) < _PAN_SNAP_THRESHOLD and abs(dy) < _PAN_SNAP_THRESHOLD:
            # Close enough — snap and stop
            self.x = self._target_x
            self.y = self._target_y
            self._target_x = None
            self._target_y = None
        else:
            self.x += dx * _PAN_LERP_SPEED
            self.y += dy * _PAN_LERP_SPEED

    def zoom_at(self, screen_x: int, screen_y: int, factor: float) -> None:
        """Zoom centered on a screen position."""
        # Get world position under cursor before zoom
        world_x, world_y = self.screen_to_world(screen_x, screen_y)

        # Apply zoom
        new_zoom = self.zoom * factor
        self.zoom = max(self.min_zoom, min(self.max_zoom, new_zoom))

        # Adjust position to keep world point under cursor
        new_world_x, new_world_y = self.screen_to_world(screen_x, screen_y)
        self.x += world_x - new_world_x
        self.y += world_y - new_world_y
