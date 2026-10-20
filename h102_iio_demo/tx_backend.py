"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       tx_backend.py
@brief      Deliver fixed TX waveforms to a native owner with optional bounded RX plotting.
@details    Preload cyclic TX once; receive within the same owner and the network budget.
            On close/failure destroy RX before STOP; RF deadlines and disconnect recovery remain native.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    0.6.0
@date       2026-10-13
"""
import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from threading import Timer
import time

from .backend import RxSession, HOST_SOURCE_SHA256, collect_session, board_for
from .model import save_json
from .session_link import SessionLink
from .tx_model import TxPlan

TX_FILES = ('board_tx.py', 'board_radio.py', 'tx_cyclic.py')
TX_SOURCES = {n:base64.b64encode((Path(__file__).parent/n).read_bytes()).decode() for n in TX_FILES}
TX_SHA256 = {n:hashlib.sha256((Path(__file__).parent/n).read_bytes()).hexdigest()
             for n in (*TX_FILES, 'tx_backend.py', 'tx_model.py', 'tx_panel.py')}


class TxLink(SessionLink):
    """Create an explicit TX request without weakening the RX actor's TX-off requirement."""
    sources = TX_SOURCES
    entrypoint = 'board_tx.py'
    start_timeout = 105

    def __init__(self, connection, info, channels, board, request, data):
        super().__init__(connection, info, channels, 'tx', 'normal', board)
        self.request, self.data = request, data

    def expected(self):
        """Preload bounded IQ into a private root session without credentials in the request."""
        return dict(info=self.info, channels=list(self.channels), mode='tx', pattern='normal',tx=self.request,
                    raw={str(ch):base64.b64encode(raw).decode() for ch,raw in self.data.items()})


def warm_tx_control(connection, info):
    """Preload TX control code in the background without locks, buffers or transmit authorization.

    An empty request warms only; each start binds fresh parameters and waveform bytes.
    Close failed channels and preserve the complete cold-start path.
    """
    link=TxLink(connection,info,(),board_for(connection),None,None)
    try:return link.warm()
    except Exception:
        link.close(stop=False);raise


class TxSession(RxSession):
    """Run fixed 1-300 second TX with optional RX observation, without live tuning or auto-restart."""
    def __init__(self, connection, info, channels, plan: TxPlan, output, event=None, prepared_link=None):
        """Validate a fresh plan before taking a warm channel, rebinding waveform and parameters.

        prepared_link reduces connection cost only, never caches transmit permission. Invalid or
        foreign identity uses the cold path; reject invalid parameters/budgets before hardware access.
        """
        self.tx_request,self.tx_data=plan.prepare(info)
        # Borrow common snapshot/thread state even without RX; actual channels stay empty afterward.
        super().__init__(connection,info,channels or (1,), 'snapshot' if not channels else 'continuous',
                         'normal',plan.seconds,output,event=event,prepared_link=prepared_link)
        self.channels=channels;self.mode='continuous';self.plan=plan

    def can_tune(self):
        """Keep TX frequency and waveform fixed; stop before changing parameters."""
        return False

    def run(self):
        """Run native TX and record start/stop outcomes separately from physical RF correctness."""
        self.started=time.monotonic();self.output.mkdir(parents=True,exist_ok=False)
        record=dict(status='RUNNING',info=deepcopy(self.info),channels=self.channels,mode='tx',pattern='normal',
            RF_TX=True,tx=self.tx_request,started_at=datetime.now(timezone.utc).isoformat(),
            host_source_sha256=dict(HOST_SOURCE_SHA256,**TX_SHA256),results=[],physical_rf_verified=False)
        candidate=self.prepared_link;self.prepared_link=None
        # Reuse only this connection's same-boot/profile idle TX entry, never promote RX into TX.
        if (isinstance(candidate,TxLink) and candidate.connection is self.connection
                and not candidate.done.is_set() and not candidate.active
                and candidate.info['boot_id']==self.info['boot_id']
                and candidate.info['configuration_id']==self.info['configuration_id']):
            self.link=candidate
            self.link.info,self.link.channels=self.info,self.channels
            self.link.request,self.link.data=self.tx_request,self.tx_data
            record['prepared_control_used']=True
        else:
            if isinstance(candidate,TxLink) and not candidate.active:candidate.close(stop=False)
            self.link=TxLink(self.connection,self.info,self.channels,self.board,self.tx_request,self.tx_data)
            record['prepared_control_used']=False
        self.link.cancel_event=self.stopping
        self.directory=self.link.directory;record['board_directory']=self.directory
        save_json(self.output/'request.json',record);timer=None
        try:
            if self.stopping.is_set(): raise RuntimeError('TX_CANCELLED_BEFORE_START')
            self.link.start();self.mark('native_permission_seconds')
            self.link.cancel_event=None
            if self.stopping.is_set():raise RuntimeError('TX_CANCELLED_DURING_PREPARATION')
            save_json(self.output/'ready.json',self.link.ready)
            self.event('ready',dict(output=str(self.output),tx=True,tx_request=self.tx_request))
            timer=Timer(self.plan.seconds,self.stop);timer.daemon=True;timer.start()
            if self.channels:
                with ThreadPoolExecutor(max_workers=len(self.channels)) as pool:
                    futures=[pool.submit(self._receive,c) for c in self.channels]
                    for future in futures:
                        try:record['results'].append(future.result())
                        except Exception:
                            self.stopping.set();raise
            else:
                while not self.stopping.wait(.1):
                    if not self.link.permitted():raise RuntimeError('TX_OWNER_PERMISSION_LOST')
            record['status']='PASS_TX_SESSION'
        except Exception as error:
            self.stopping.set();record.update(status='FAIL_TX_SESSION',error=str(error))
        finally:
            if timer:timer.cancel()
            self.closing.set();self.mark('cleanup_started_seconds')
            try:
                manager=self.link.close()
                native=manager['records'] if manager and manager.get('records') else collect_session(self.board,self.directory,self.info['boot_id'])
                save_json(self.output/'board-records.json',native)
                post=native.get('post.json',{})
                record['recovery_confirmed']=bool(post.get('passed') and post.get('rf_off')
                    and post.get('settings_restored') and post.get('configuration_unchanged'))
                record['rf_off_confirmed']=post.get('rf_off',False);record['final_radio']=post.get('radio')
                if not record['recovery_confirmed'] or not manager or manager.get('returncode'):
                    record.update(status='FAIL_TX_SESSION',recovery_error='Native TX or recovery failed; see board-records.json')
                record['native_returncode']=manager.get('returncode') if manager else None
                if manager and 'request.json' not in native and native.get('main.json',{}).get('status')=='failed':
                    # Native code performs no hardware writes before request persistence; contention is not RF recovery failure.
                    record.update(recovery_confirmed=True,recovery_required=False,rf_off_confirmed=None,
                        hardware_changed=False,error=native['main.json']['error'])
                    record.pop('recovery_error',None)
            except Exception as error:
                record.update(status='FAIL_TX_SESSION',recovery_confirmed=False,recovery_error=str(error))
            self.mark('finished_seconds');self.board.password=None
            record.update(timings=dict(self.timings),control_timings=dict(self.link.timings),
                          finished_at=datetime.now(timezone.utc).isoformat())
            save_json(self.output/'result.json',record)
        self.event('finished',record);return record


# End of file: tx_backend.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
