from abc import ABC,abstractmethod
class SportsProvider(ABC):
    name='base'
    @abstractmethod
    def list_matches(self,start,end,sport='football'): raise NotImplementedError
    @abstractmethod
    def match_details(self,match_id): raise NotImplementedError
    @abstractmethod
    def match_stats(self,match_id): raise NotImplementedError
    @abstractmethod
    def lineups(self,match_id): raise NotImplementedError
