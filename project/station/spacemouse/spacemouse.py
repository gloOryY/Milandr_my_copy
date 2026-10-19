import threading
import time
import struct

try:
    import hid
except Exception:
    hid = None

from project.application.addition.logger import logger
from project.station.robot.movements import move_robot_to_coordinates


class SpaceMouseController:
    def __init__(
        self,
        config,
        robot,
        robot_command_queue,
        update_slider,
        show_error,
        threshold=180,
        release=60,
        cooldown=0.5,
        invert_x=False,
        invert_y=True,
        invert_z=True,
    ):
        self.config = config
        self.robot = robot
        self.robot_command_queue = robot_command_queue
        self.update_slider = update_slider
        self.show_error = show_error

        self.threshold = threshold
        self.release = release
        self.cooldown = cooldown

        self.invert_x = invert_x
        self.invert_y = invert_y
        self.invert_z = invert_z

        self.enabled = False
        self._started = False

    def start(self):
        if self._started:
            return

        if hid is None:
            logger.error("SpaceMouse: пакет hidapi не установлен. Выполните: python -m pip install hidapi")
            return

        self._started = True
        threading.Thread(target=self._listener, daemon=True).start()

    def _score(self, dev):
        score = 0
        product = str(dev.get("product_string") or "").lower()

        if "spacemouse compact" in product:
            score += 100
        elif "spacemouse" in product:
            score += 80
        elif "space navigator" in product:
            score += 50

        if dev.get("vendor_id") == 0x256F:
            score += 20

        if dev.get("usage_page") == 0x0001:
            score += 10

        if dev.get("interface_number") == 0:
            score += 2

        return score

    def _move(self, dx=0, dy=0, dz=0):
        page = self.config.page
        current_step = self.config.movement_step

        if current_step == "crystal_size":
            try:
                step_x = float(self.config.wafer_params["x_distance"])
            except Exception:
                step_x = 1.0

            try:
                step_y = float(self.config.wafer_params["y_distance"])
            except Exception:
                step_y = 1.0

            step_z = 1.0
        else:
            try:
                step_value = float(current_step)
            except Exception:
                step_value = 0.1

            step_x = step_value
            step_y = step_value
            step_z = step_value

        target_x = self.config.current_coordinates["x"] + dx * step_x
        target_y = self.config.current_coordinates["y"] + dy * step_y
        target_z = self.config.current_coordinates["z"] + dz * step_z

        # logger.debug(
        #     f"SpaceMouse: dx={dx}, dy={dy}, dz={dz}, "
        #     f"step={current_step}, "
        #     f"target=({target_x:.2f}, {target_y:.2f}, {target_z:.2f})"
        # )

        def execute_command():
            move_robot_to_coordinates(
                robot=self.robot,
                config=self.config,
                x=target_x,
                y=target_y,
                z=target_z
            )

            updates = {}

            if dx != 0:
                updates["x"] = target_x

            if dy != 0:
                updates["y"] = target_y

            if dz != 0:
                updates["z"] = target_z

            if updates:
                self.update_slider(updates)

        def on_error(e):
            self.show_error(
                "Ошибка Манипулятора",
                str(e),
                page,
                self.config
            )

        self.robot_command_queue.put(execute_command, error_callback=on_error)

    def _listener(self):
        known_vendor_ids = {0x256F, 0x046D}

        while True:
            device = None

            try:
                candidates = []

                for dev in hid.enumerate():
                    vid = dev.get("vendor_id")
                    product = str(dev.get("product_string") or "").lower()

                    if vid in known_vendor_ids or "spacemouse" in product:
                        candidates.append(dev)

                if not candidates:
                    time.sleep(2)
                    continue

                candidates.sort(key=self._score, reverse=True)

                device = hid.device()
                device.open_path(candidates[0]["path"])

                logger.info("SpaceMouse: устройство открыто")

                axes = [0, 0, 0, 0, 0, 0]
                armed = True
                last_command = 0.0

                while True:
                    raw = device.read(64, 100)

                    if not raw:
                        if not armed and time.time() - last_command > 1.0:
                            armed = True

                        continue

                    data = bytes(raw)
                    report_id = data[0]
                    payload = data[1:]

                    if len(payload) >= 12:
                        axes[:] = struct.unpack_from("<6h", payload, 0)

                    elif report_id == 1 and len(payload) >= 6:
                        axes[0:3] = struct.unpack_from("<3h", payload, 0)

                    elif report_id == 2 and len(payload) >= 6:
                        axes[3:6] = struct.unpack_from("<3h", payload, 0)

                    if not self.enabled:
                        armed = True
                        continue

                    x, y, z = axes[0], axes[1], axes[2]
                    max_abs = max(abs(x), abs(y), abs(z))

                    if not armed:
                        if max_abs < self.release:
                            armed = True

                        continue

                    if max_abs < self.threshold:
                        continue

                    now = time.time()

                    if now - last_command < self.cooldown:
                        continue

                    if abs(x) >= abs(y) and abs(x) >= abs(z):
                        dx = 1 if x > 0 else -1
                        dy = 0
                        dz = 0

                        if self.invert_x:
                            dx = -dx

                    elif abs(y) >= abs(x) and abs(y) >= abs(z):
                        dx = 0
                        dy = 1 if y > 0 else -1
                        dz = 0

                        if self.invert_y:
                            dy = -dy

                    else:
                        dx = 0
                        dy = 0
                        dz = 1 if z > 0 else -1

                        if self.invert_z:
                            dz = -dz

                    self._move(dx=dx, dy=dy, dz=dz)

                    armed = False
                    last_command = now

            except Exception as e:
                logger.error(f"SpaceMouse: ошибка чтения/подключения: {e}")

            finally:
                if device is not None:
                    try:
                        device.close()
                    except Exception:
                        pass

            time.sleep(2)