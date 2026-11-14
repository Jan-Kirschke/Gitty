from dataclasses import dataclass
from typing import Optional
from enum import Enum


class MessageType(Enum):
    CHAT = "chat"
    SYSTEM = "system"
    ERROR = "error"
    PING = "ping"
    PONG = "pong"


@dataclass
class Message:
    msg_type: MessageType
    sender: str
    content: str
    target: Optional[str] = None
    rating: int = 0
    timestamp: Optional[str] = None

    def to_json(self) -> dict:
        return {
            "type": self.msg_type.value,
            "from": self.sender,
            "to": self.target,
            "msg": self.content,
            "rating": self.rating,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_json(cls, data: dict) -> "Message":
        return cls(
            msg_type=MessageType(data.get("type", "chat")),
            sender=data.get("from", ""),
            content=data.get("msg", ""),
            target=data.get("to"),
            rating=data.get("rating", 0),
            timestamp=data.get("timestamp"),
        )


@dataclass
class ClientInfo:
    username: str
    socket: object
    connected_at: float
    last_activity: float
    is_active: bool = True
