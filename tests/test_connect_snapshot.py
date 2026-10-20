"""Test single-actor API snapshot ownership and cleanup on failure, without SSH."""
from copy import deepcopy
import pytest
from h102_iio_demo import backend
from h102_control import compat
from test_gui import fixture_state


@pytest.mark.parametrize('case',['pass','mismatch','api-failure','ready-failure'])
def test_snapshot_and_failure_cleanup(tmp_path,monkeypatch,case):
    state=fixture_state();state['actual']['identity']={'boot_id':'offline'};events=[]
    class Client:
        def __init__(self,connection):assert connection.host=='offline'
        def status(self):
            events.append('api-status')
            if case=='api-failure':raise OSError('injected API failure')
            return deepcopy(state)
    class Link:
        def __init__(self):
            snapshot=deepcopy(state['actual']);snapshot.update(parameters=state['info']['parameters'],radio=state['info']['radio'])
            if case=='mismatch':snapshot['identity']['boot_id']='changed'
            self.ready={'connection_snapshot':snapshot,'channels':[1,2]}
    def prepare(connection,info,channels,output,*,discover_radio):
        assert discover_radio and connection.host=='offline'
        events.append('native-prepare')
        if case=='ready-failure':raise RuntimeError('injected native failure')
        return Link()
    monkeypatch.setattr(compat,'Client',Client)
    monkeypatch.setattr(backend,'prepare_idle_control',prepare)
    monkeypatch.setattr(backend,'close_idle_control',lambda _:events.append('native-close'))
    connection=backend.Connection('offline')
    if case=='pass':
        result=backend.inspect(connection,None,True,tmp_path/'control')
        assert result['_idle_link'].channels==(1,2)
        assert events==['api-status','native-prepare']
        backend.close_idle_control(result['_idle_link'])
    else:
        with pytest.raises((RuntimeError,OSError)):backend.inspect(connection,None,True,tmp_path/'control')
        assert ('native-close' in events)==(case=='mismatch')
    assert set(connection.__dict__)=={'host','port'}
