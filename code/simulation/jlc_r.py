"""Public JLC-R controller with topology-weighted source competition by default."""
from source_protection import SourceProtectedJLCR
from topology_weighted import TopologyWeightedJLCR


class JLCR(TopologyWeightedJLCR):
    """Complete controller; explicit modes retain the matched internal ablations."""

    def __init__(self,*args,source_protection='spatial',**kwargs):
        if source_protection not in ('spatial','unweighted','off','admission','headroom','priority','joint'):
            raise ValueError('Unknown source protection mode')
        self.public_source_mode=source_protection
        self._uses_source_competition=source_protection in ('spatial','unweighted')
        if self._uses_source_competition:
            TopologyWeightedJLCR.__init__(self,*args,**kwargs)
            if source_protection=='unweighted':self.origin_hops[:]=1
        else:
            SourceProtectedJLCR.__init__(self,*args,source_protection=source_protection,**kwargs)

    def _protected_packet(self,node):
        cls=TopologyWeightedJLCR if self._uses_source_competition else SourceProtectedJLCR
        return cls._protected_packet(self,node)

    def _guard_exchange(self,sender,receiver,packet):
        cls=TopologyWeightedJLCR if self._uses_source_competition else SourceProtectedJLCR
        return cls._guard_exchange(self,sender,receiver,packet)

    def metrics(self):
        result=SourceProtectedJLCR.metrics(self)
        result['source_protection']=self.public_source_mode
        result['source_protection_scope']='Topology-weighted local forwarding-debt competition' if self.public_source_mode=='spatial' else 'Explicit matched internal control'
        return result


__all__=['JLCR']
