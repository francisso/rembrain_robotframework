import logging
import typing as T
from collections import namedtuple
from multiprocessing import Queue
from threading import Thread
from uuid import uuid4

from rembrain_robot_framework.models.personal_message import PersonalMessage
from rembrain_robot_framework.services.watcher import Watcher

from rembrain_robot_framework.util.stack_monitor import StackMonitor


class RobotProcess:
    def __init__(
            self,
            name: str,
            shared_objects: dict,
            consume_queues: T.Dict[str, Queue],
            publish_queues: T.Dict[str, T.List[Queue]],
            system_queues: T.Dict[str, Queue],
            watcher: Watcher,
            *args,
            **kwargs
    ):
        self.name: str = name

        self._consume_queues: T.Dict[str, Queue] = consume_queues  # queues for reading
        self._publish_queues: T.Dict[str, T.List[Queue]] = publish_queues  # queues for writing

        self._shared: T.Any = namedtuple('_', shared_objects.keys())(**shared_objects)

        self._system_queues: T.Dict[str, Queue] = system_queues
        self._received_personal_messages = {}

        self.queues_to_clear: T.List[str] = []  # in case of exception this queues are cleared
        self.log = logging.getLogger(f"{self.__class__.__name__} ({self.name})")

        self._stack_monitor: T.Optional[StackMonitor] = None
        if "monitoring" in kwargs and kwargs['monitoring']:
            self._init_monitoring(self.name)

        self.watcher = watcher

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
        if self._stack_monitor:
            self._stack_monitor.stop_monitoring()

        self.close_objects()
        self.clear_queues()

    # todo it's ridiculous - free_resources may be called with super()
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

    def publish(self, message: T.Any, queue_name: T.Optional[str] = None, clear_on_overflow: bool = False,
                is_personal: bool = False) -> T.Optional[str]:
        if len(self._publish_queues.keys()) == 0:
            self.log.error(f"Process \"{self.name}\" has no queues to write.")
            return

        if queue_name is None:
            if len(self._publish_queues.keys()) != 1:
                self.log.error(f"Process \"{self.name}\" has more than one write queue. Specify a write queue name.")
                return

            queue_name = list(self._publish_queues.keys())[0]

        personal_id: T.Optional[str] = None
        if is_personal:
            personal_id = str(uuid4())
            message = PersonalMessage(id=personal_id, client_process=self.name, data=message)

        print(queue_name)
        print(self._publish_queues[queue_name])
        for q in self._publish_queues[queue_name]:
            if clear_on_overflow:
                while q.full():
                    q.get()

            q.put(message)

        return personal_id

    def consume(self, queue_name: T.Optional[str] = None, clear_all_messages: bool = False) -> T.Any:
        if len(self._consume_queues.keys()) == 0:
            # todo maybe there should be exception here?
            self.log.error(f"Process \"{self.name}\" has no queues to read.")
            return

        if queue_name is None:
            if len(self._consume_queues.keys()) != 1:
                # todo maybe there should be exception here?
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

        # if consume queue
        if consume_queue_name:
            if not self.has_consume_queue(consume_queue_name):
                raise Exception(f"Consume queue with name = '{consume_queue_name}' does not exist.")

            # TODO check if it's used anywhere
            return self._consume_queues[consume_queue_name].full()

        # if publish queue
        if not self.has_publish_queue(publish_queue_name):
            raise Exception(f"Publish queue with name = '{publish_queue_name}' does not exist.")

        for q in self._publish_queues[publish_queue_name]:
            if q.full():
                return True

        return False

    # todo exceptions or logging
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
            raise Exception(f"Process \"{self.name}\" has no queues to read.")

        if consume_queue_name is None:
            if len(self._consume_queues.keys()) != 1:
                raise Exception(f"Process '{self.name}' has more than one read queue. Specify a consume queue name.")

            consume_queue_name = list(self._consume_queues.keys())[0]

        return self._consume_queues[consume_queue_name].empty()

    def _init_monitoring(self, name):
        """
        Initializes stack monitoring
        This feature will sample the stacks of all threads in the process for a period, then log them out
        """
        self._stack_monitor = StackMonitor(name)
        self._stack_monitor.start_monitoring()

    def publish_to_system_queue(self, personal_id: str, client_process: str, data: T.Any) -> None:
        self._system_queues[client_process].put(
            PersonalMessage(id=personal_id, client_process=client_process, data=data)
        )

    def consume_from_system_queue(self, personal_id: str) -> T.Any:
        if personal_id in self._received_personal_messages:
            message: PersonalMessage = self._received_personal_messages[personal_id]
            del self._received_personal_messages[personal_id]
            return message.data

        while True:
            # todo exception or logging?
            if len(self._received_personal_messages) > 50:
                raise Exception(f"Overflow of personal messages for '{self.name}'!")

            message: PersonalMessage = self._system_queues[self.name].get()
            if message.id == personal_id:
                return message.data
            else:
                self._received_personal_messages[message.id] = message.data

    def heartbeat(self, message: str):
        Thread(target=self.watcher.notify, daemon=True, args=(message,)).start()
