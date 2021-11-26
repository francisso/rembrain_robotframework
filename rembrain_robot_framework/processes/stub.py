from time import sleep

from rembrain_robot_framework import RobotProcess


class StubProcess(RobotProcess):
    """ It is just stub without any benefit work."""

    def __init__(self, eternal_loop: bool = True, *args, **kwargs):
        super(StubProcess, self).__init__(*args, **kwargs)
        self.eternal_loop = eternal_loop

    def run(self):
        self.log.info(f"{self.__class__.__name__} started, name: {self.name}.")

        while self.eternal_loop:
            sleep(20)
