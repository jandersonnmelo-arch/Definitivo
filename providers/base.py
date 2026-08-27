from abc import ABC, abstractmethod

class FootballProvider(ABC):
    name = "base"
    @abstractmethod
    def available(self): ...
    @abstractmethod
    def matches(self, date_from, date_to, competition=None): ...
    def match_details(self, match_id): return {"stats":[],"players":[]}
