import time
import typing as T
from datetime import datetime, timezone

from rembrain_robot_framework import RobotProcess
from rembrain_robot_framework.pack import Packer


class VideoPacker(RobotProcess):
    """
    In: Tuple of two images (numpy raw pixel arrays)
    *ASSUMES THAT THERE'S A SHARED CAMERA FIELD*
    Does: Packs the two images + camera data into a single package using a packer specified in pack_type
    Out: Binary package of the two frames + camera
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.packets_sent = 0
        self.last_timed: float = time.time()
        self.packer = Packer(kwargs.get("pack_type"))

    def run(self):
        self.log.info(f"{self.__class__.__name__} started, name: {self.name}.")

        while True:
            camera = {}
            if hasattr(self.shared, 'camera'):
                camera: T.Any = self.shared.camera.copy()

            result = self.consume()
            if len(result) == 2:
                rgb, depth = result
            elif len(result) == 3:
                rgb, depth, camera = result
            else:
                raise Exception('video_packer consumes tuples with 2 or 3 elements')

            camera["time"] = datetime.now(timezone.utc).timestamp()
            buffer: bytes = self.packer.pack(rgb, depth, camera)
            self.publish(buffer)

            self.packets_sent += 1
            if self.packets_sent % 300 == 0:
                self.log.info(f"Current video sending rate is {300 / (time.time() - self.last_timed)} fps.")
                self.last_timed = time.time()
