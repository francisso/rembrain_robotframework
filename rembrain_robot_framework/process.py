import logging
import typing as T
from collections import namedtuple
from multiprocessing import Queue

from rembrain_robot_framework.util.stack_monitor import StackMonitor


class RobotProcess:
    def __init__(
            self,
            name: str,
            shared_objects: dict,
            consume_queues: T.Dict[str, Queue],
            publish_queues: T.Dict[str, T.List[Queue]],
            *args,
            **kwargs
    ):
        self.name: str = name

        self._consume_queues: T.Dict[str, Queue] = consume_queues  # queues for reading
        self._publish_queues: T.Dict[str, T.List[Queue]] = publish_queues  # queues for writing

        self._shared: T.Any = namedtuple('_', shared_objects.keys())(**shared_objects)
        self.queues_to_clear: T.List[str] = []  # in case of exception this queues are cleared
        self.log = logging.getLogger(f"{self.__class__.__name__} ({self.name})")
        self._stack_monitor: T.Optional[StackMonitor] = None
        if "monitoring" in kwargs:
            self._init_monitoring(kwargs["monitoring"])

    def run(self) -> None:
        raise NotImplementedError()

    @property
    def consume_queues(self):
        return self._consume_queues

    @property
    def publish_queues(self):
        return self._publish_queues

    @property
    def shared(self):
        # TODO review this method to get logging of shared object usage
        return self._shared

    def free_resources(self) -> None:
        """
        It frees all occupied resources.
        """
        if not self._stack_monitor:
            self._stack_monitor.stop_monitoring()
        self.close_objects()
        self.clear_queues()

    def close_objects(self) -> None:
        """It can be overridden in process implementation."""
        pass

    def clear_queues(self) -> None:
        if len(self.queues_to_clear) > 0:
            self.log.info(f"Clearing of queues: {self.queues_to_clear}.")

            for queue in self.queues_to_clear:
                self.clear_queue(queue)

    def clear_queue(self, queue: str) -> None:
        if queue in self._consume_queues:
            while not self._consume_queues[queue].empty():
                self._consume_queues[queue].get(timeout=2.0)

        elif queue in self._publish_queues:
            for q in self._publish_queues[queue]:
                while not q.empty():
                    q.get(timeout=2.0)

    def publish(self, message: T.Any, queue_name: T.Optional[str] = None, clear_on_overflow: bool = False) -> None:
        if len(self._publish_queues.keys()) == 0:
            self.log.error(f"Process \"{self.name}\" has no queues to write to.")
            return

        if queue_name is None:
            if len(self._publish_queues.keys()) != 1:
                self.log.error(f"Process \"{self.name}\" has more than one write queue. Specify a write queue name.")
                return

            queue_name = list(self._publish_queues.keys())[0]

        for q in self._publish_queues[queue_name]:
            if clear_on_overflow:
                while q.full():
                    q.get()

            q.put(message)

    def consume(self, queue_name: T.Optional[str] = None, clear_all_messages: bool = False) -> T.Any:
        if len(self._consume_queues.keys()) == 0:
            self.log.error(f"Process \"{self.name}\" has no queues to read from.")
            return

        if queue_name is None:
            if len(self._consume_queues.keys()) != 1:
                self.log.error(f"Process \"{self.name}\" has more than one read queue. Specify a read queue name.")
                return

            queue_name = list(self._consume_queues.keys())[0]

        message: str = self._consume_queues[queue_name].get()
        if clear_all_messages:
            while not self._consume_queues[queue_name].empty():
                message = self._consume_queues[queue_name].get()

        return message

    def has_consume_queue(self, queue_name: str) -> bool:
        return queue_name in self._consume_queues

    def has_publish_queue(self, queue_name: str) -> bool:
        return queue_name in self._publish_queues

    def is_full(
            self,
            *,
            publish_queue_name: T.Optional[str] = None,
            consume_queue_name: T.Optional[str] = None
    ) -> bool:
        if publish_queue_name is None and consume_queue_name is None:
            raise Exception("None of params was got!")

        if publish_queue_name and consume_queue_name:
            raise Exception("Only one of params must set!")

        if consume_queue_name:
            # TODO check if it's used anywhere
            return self._consume_queues[consume_queue_name].full()

        for q in self._publish_queues[publish_queue_name]:
            if q.full():
                return True

        return False

    def is_empty(self, consume_queue_name: T.Optional[str] = None):
        """
        Checks inter-process queue is empty.
        It's only possible to check a consumer queue because there is no sense in checking publishing queues

        :param consume_queue_name: Name of an input queue. If it's none - check the only one queue
        that is set as input in config
        :type consume_queue_name: str
        :rtype: Bool
        """
        if len(self._consume_queues.keys()) == 0:
            raise Exception(f"Process \"{self.name}\" has no queues to read from.")

        if consume_queue_name is None:
            if len(self._consume_queues.keys()) != 1:
                raise Exception(f"Process '{self.name}' has more than one read queue. Specify a consume queue name.")

            consume_queue_name = list(self._consume_queues.keys())[0]

        return self._consume_queues[consume_queue_name].empty()

    def _init_monitoring(self, monitor_args: T.Union[bool, dict]):
        """
        Initializes stack monitoring
        This feature will sample the stacks of all threads in the process for a period, then log them out
        You can look at the available arguments in the StackMonitor constructor
        """
        if type(monitor_args) is bool:
            if not monitor_args:
                return
            self._stack_monitor = StackMonitor()
        else:
            self._stack_monitor = StackMonitor(**monitor_args)
        self._stack_monitor.start_monitoring()

