"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       session_link.py
@brief      Maintain a bounded device-API channel and native RX heartbeat.
@details    One IO thread sends pulses/commands and matches replies; full IQ travels separately through libiio.
            Do not reconnect or restart buffers on failure; credentials use authentication stdin only and never enter logs.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    0.8.0
@date       2026-10-14
"""
import base64
import json
from pathlib import Path
from queue import Queue,Empty
import shlex
from threading import Event,Lock,Thread
import time
import uuid

from .board_session import AUTO_TUNE_SECONDS

SESSION_SOURCES={n:base64.b64encode((Path(__file__).parent/n).read_bytes()).decode()
                 for n in ('board_session.py','board_radio.py','board_capture.py')}
"""Freeze loaded board payloads so later source edits cannot change an active session's identity."""

class SessionLink:
    """Own one API channel per session; owner-thread start/close and thread-safe permit reads.

    Keep at most one ready/finished response and one pending tune; do not accumulate pulse replies.
    Bound recv to 64 KiB and stderr tail to 8 KiB. Disconnection waits for native timeout recovery without reconnecting.
    """
    sources = SESSION_SOURCES
    entrypoint = 'board_session.py'
    start_timeout = 35

    def __init__(self,connection,info,channels,mode,pattern,board):
        self.connection,self.info,self.channels=connection,info,channels
        self.mode,self.pattern,self.board=mode,pattern,board
        self.directory='/run/h102-gui-session-'+uuid.uuid4().hex
        self.client=None;self.channel=None;self.thread=None
        self.ready=None;self.finished=None;self.error=None;self.stderr=''
        self.timings={};self.started=0.0
        self.warm_event=Event();self.active=False
        self.last_health=0.0;self.ready_event=Event();self.done=Event();self.terminate=Event()
        self.outgoing=Queue(maxsize=4);self.pending={};self.lock=Lock()
        self.cancel_event=None

    def warm(self):
        """Warm a fixed control channel without hardware checks, board locks or RX authorization."""
        from h102_control.compat import warm
        return warm(self)

    def start(self):
        """Run complete checks over an idle warmed channel; establish the channel first when necessary."""
        if not self.thread:self.warm()
        if self.done.is_set() or self.active:raise RuntimeError('SESSION_LINK_NOT_IDLE')
        self.active=True;self.started=time.monotonic();self.timings['start_requested_monotonic']=self.started
        expected=self.expected()
        self.outgoing.put_nowait(dict(action='start',expected=expected))
        if not self.ready_event.wait(self.start_timeout) or self.ready is None:
            self.close()
            native_error=(self.finished or {}).get('records',{}).get('main.json',{}).get('error')
            raise RuntimeError('Native session preparation failed: '+str(native_error or self.error or self.stderr)[-700:])
        if (self.ready['identity']['boot_id']!=self.info['boot_id']
                or self.ready['configuration_id']!=self.info['configuration_id']):
            self.close();raise RuntimeError('SESSION_READY_IDENTITY_CHANGED')
        until=time.monotonic()+6
        while not self.permitted() and not self.done.is_set() and time.monotonic()<until:time.sleep(.05)
        if not self.permitted():self.close();raise RuntimeError('Native heartbeat health is unconfirmed')

    def expected(self):
        """Preserve the RX request contract; the TX subclass supplies its own frozen request."""
        return dict(info=self.info,channels=list(self.channels),mode=self.mode,pattern=self.pattern,
                    discover_radio=getattr(self,'discover_radio',False))

    def _io(self):
        """Sole channel IO thread sends pulses every two seconds and parses replies without unlimited logs."""
        buffer=b'';next_pulse=0;cancel_sent=False
        try:
            while not self.terminate.is_set():
                now=time.monotonic()
                if now>=next_pulse:
                    self.channel.sendall(json.dumps(dict(action='pulse'))+'\n');next_pulse=now+2
                try:value=self.outgoing.get_nowait()
                except Empty:value=None
                if value:self.channel.sendall(json.dumps(value)+'\n')
                cancel_event=self.cancel_event
                if self.active and cancel_event is not None and cancel_event.is_set() and not cancel_sent:
                    self.channel.sendall(json.dumps(dict(action='stop'))+'\n');cancel_sent=True
                if self.channel.recv_ready():
                    buffer+=self.channel.recv(65536)
                    while b'\n' in buffer:
                        line,buffer=buffer.split(b'\n',1)
                        if len(line)>65536:raise RuntimeError('CONTROL_RESPONSE_TOO_LARGE')
                        if not line.strip():continue
                        value=json.loads(line);kind=value['type']
                        if kind=='warm':self.warm_event.set()
                        elif kind=='bootstrap':self.timings['root_bootstrap_seconds']=time.monotonic()-self.started
                        elif kind=='ready':
                            self.ready=value['ready']
                            health=value.get('health')
                            if health and health.get('permitted') and 0<=value['now_ns']-health['checked_ns']<3_000_000_000:
                                self.last_health=time.monotonic()
                            self.timings['native_ready_seconds']=time.monotonic()-self.started
                            self.ready_event.set()
                        elif kind=='pulse':
                            health=value['health']
                            if health and 0<=value['now_ns']-health['checked_ns']<3_000_000_000:
                                self.last_health=time.monotonic()
                        elif kind=='reply':
                            with self.lock:pending=self.pending.get(value['id'])
                            if pending:
                                if not value['result'].get('permitted'):raise RuntimeError('TUNE_PERMISSION_MISSING')
                                self.last_health=time.monotonic()
                                pending['result']=value['result'];pending['event'].set()
                        elif kind=='finished':self.finished=value['result']
                    if len(buffer)>65536:raise RuntimeError('CONTROL_RESPONSE_TOO_LARGE')
                if self.channel.recv_stderr_ready():
                    self.stderr=(self.stderr+self.channel.recv_stderr(8192).decode(errors='replace'))[-8192:]
                if self.channel.exit_status_ready() and not self.channel.recv_ready():
                    status=self.channel.recv_exit_status()
                    if status or (self.active and self.finished is None):raise RuntimeError('SESSION_CONTROL_EXIT_'+str(status)+': '+self.stderr[-700:])
                    break
                time.sleep(.002 if self.mode=='sweep' else .01)
        except Exception as error:self.error=error
        finally:self.done.set();self.ready_event.set();self.warm_event.set()

    def permitted(self):
        """Grant data operations only to this live session with fresh native health."""
        return self.ready is not None and not self.done.is_set() and time.monotonic()-self.last_health<8

    def guard(self, action, channel):
        """Begin/end continuity windows while producer buffers are alive; serialize requests for both channels."""
        if action not in ('begin','arm','end'):raise ValueError('GUARD_ACTION')
        return self._command(dict(action='guard_'+action,channel=channel))['guard']

    def sweep_setup(self, plan):
        """Warm board FFT plan/local context without tuning or creating data buffers."""
        return self._command(dict(action='sweep_setup',plan=plan,centers=[]))

    def sweep_batch(self, plan, centers):
        """Run board-side short FFT batches of at most 32 segments and return final-bin peaks."""
        return self._command(dict(action='sweep_batch',plan=plan,centers=centers))

    def tune(self,frequency,channels=None):
        """Await actor readback after buffers stop; auto commands use the calibration budget without implicit retries."""
        return self._command(dict(action='tune',frequency_hz=frequency,channels=channels))

    def activate_rx(self,info,channels,pattern):
        """Convert verified idle control to RX ownership without rebuilding locks or hardware context."""
        if not self.active or self.mode!='idle_tune' or pattern not in ('normal','ramp16'):
            raise RuntimeError('RX_ACTIVATION_STATE')
        reply=self._command(dict(action='activate_rx',info=info,channels=list(channels),pattern=pattern))
        if not reply.get('activated_rx'):raise RuntimeError('RX_ACTIVATION_NOT_CONFIRMED')
        self.info,self.channels,self.mode,self.pattern=info,channels,'live',pattern
        self.ready=reply['ready']
        return reply

    def _command(self,value):
        """Submit one bounded command serially; update host state only after acknowledgement."""
        identifier=uuid.uuid4().hex;pending=dict(event=Event())
        with self.lock:
            if self.pending:raise RuntimeError('TUNE_ALREADY_PENDING')
            self.pending[identifier]=pending
        try:
            self.outgoing.put_nowait(dict(value,id=identifier))
            seconds=(AUTO_TUNE_SECONDS+15 if value['action'] in ('tune','sweep_batch') and
                     self.info['radio'].get('initial_calibrations')=='auto' else 45)
            until=time.monotonic()+seconds
            while not pending['event'].wait(.1):
                if self.done.is_set() or time.monotonic()>=until:
                    detail=(self.finished or {}).get('records',{}).get('main.json',{}).get('error')
                    raise RuntimeError('Tuning failed: '+str(detail or self.error or 'TUNE_DEADLINE'))
            # Actual tuning responses recheck identity/profile/TX/deadline and provide fresh permission.
            reply=pending['result']
            until=time.monotonic()+6
            while not self.permitted() and not self.done.is_set() and time.monotonic()<until:time.sleep(.05)
            if not self.permitted():raise RuntimeError('Heartbeat health after tuning is unconfirmed')
            return reply
        finally:
            with self.lock:self.pending.pop(identifier,None)

    def close(self,stop=True):
        """Stop and await native post; stop=False simulates disconnect without renewal or reconnection."""
        if self.thread and not self.done.is_set():
            if stop:
                self.outgoing.put(dict(action='stop'),timeout=1)
                self.done.wait(95 if self.active else 2)
            else:
                self.terminate.set()
                if self.channel:self.channel.close()
                self.done.wait(10)
        self.terminate.set()
        if self.client:self.client.close()
        if self.thread:self.thread.join(timeout=10)
        return self.finished


# End of file: session_link.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
