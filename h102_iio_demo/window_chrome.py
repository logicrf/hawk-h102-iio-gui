"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       window_chrome.py
@brief      Implement the custom title bar and frameless window operations.
@details    Prefer native Qt move/resize with bounded geometry fallback; never touch device workers.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    0.6.0
@date       2026-10-15
"""
from pathlib import Path
from PySide6 import QtCore, QtGui, QtWidgets
from .i18n import CHINESE


class WindowChrome(QtWidgets.QWidget):
    """Own titlebar/event filters with the main window; native actions require mouse gestures."""
    def __init__(self, owner):
        super().__init__(owner)
        self.owner=owner
        self.drag=None
        self.setObjectName('h102-titlebar')
        self.setFixedHeight(46)
        self.setMouseTracking(True)
        layout=QtWidgets.QHBoxLayout(self);layout.setContentsMargins(14,0,6,0);layout.setSpacing(8)
        icon=QtGui.QIcon(str(Path(__file__).parent.parent/'assets/brand/logicrf-logo.svg'))
        owner.setWindowIcon(icon)
        self.logo=QtWidgets.QLabel(self);self.logo.setObjectName('logicrf-logo')
        self.logo.setFixedSize(22,22)
        pixmap=icon.pixmap(40,40);pixmap.setDevicePixelRatio(2)
        self.logo.setPixmap(pixmap);self.logo.setAlignment(QtCore.Qt.AlignCenter)
        self.logo.setStyleSheet('background:transparent')
        self.logo.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        layout.addWidget(self.logo);layout.addSpacing(2)
        self.brand=QtWidgets.QLabel('LogicRF  ·  Hawk H102',self)
        self.brand.setStyleSheet('font-size:14px;font-weight:600;color:#ccdee8;background:transparent')
        self.brand.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        layout.addWidget(self.brand)
        version=QtWidgets.QLabel('IIO RX / TX  /  v0.8',self)
        version.setStyleSheet('color:#718a9c;background:transparent;font-size:11px')
        version.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        layout.addStretch();layout.addWidget(version);layout.addSpacing(12)
        self.language = QtWidgets.QComboBox(self)
        self.language.setObjectName('interface-language')
        self.language.setAccessibleName("Interface language")
        self.language.setToolTip("Interface language")
        self.language.addItem(CHINESE['Simplified Chinese'], 'zh_CN')
        self.language.addItem('English', 'en')
        self.language.setFixedWidth(114)
        self.language.setStyleSheet('QComboBox{font-size:12px;padding:4px 7px;background:#1b2b35;border:0;border-radius:5px;}')
        self.language.currentIndexChanged.connect(
            lambda: owner.i18n.set_language(self.language.currentData()))
        layout.addWidget(self.language)
        self.minimize=self._button('−',"Minimize",owner.showMinimized)
        self.maximize=self._button('□',"Maximize / restore",self.toggle_maximize)
        self.close_button=self._button('×',"Close (stop RX/TX and restore first)",owner.close)
        self.close_button.setObjectName('h102-close-window')
        for button in (self.minimize,self.maximize,self.close_button):layout.addWidget(button)
        QtWidgets.QApplication.instance().installEventFilter(self)

    def _button(self,text,tip,callback):
        """Route close through the original receiver cleanup rather than destroying the owner."""
        button=QtWidgets.QToolButton(self);button.setText(text);button.setToolTip(tip)
        button.setFixedSize(36,32);button.setAutoRaise(True);button.clicked.connect(callback)
        return button

    def toggle_maximize(self):
        """Retain normal Qt geometry for restoration rather than manually filling the work area."""
        if self.owner.isMaximized():self.owner.showNormal()
        else:self.owner.showMaximized()
        self.maximize.setText('❐' if self.owner.isMaximized() else '□')

    def edges(self,point):
        """Resize within a six-pixel normal-window border; preserve maximized content events."""
        edge=QtCore.Qt.Edge(0)
        if self.owner.isMaximized():return edge
        if point.x()<6:edge|=QtCore.Qt.LeftEdge
        elif point.x()>=self.owner.width()-6:edge|=QtCore.Qt.RightEdge
        if point.y()<6:edge|=QtCore.Qt.TopEdge
        elif point.y()>=self.owner.height()-6:edge|=QtCore.Qt.BottomEdge
        return edge

    def eventFilter(self,obj,event):
        """Handle only this main window's resize edges; charts/panel controls receive normal events."""
        if not isinstance(obj,QtWidgets.QWidget) or obj.window()!=self.owner or not self.owner.isVisible():return False
        kind=event.type()
        if kind not in (QtCore.QEvent.MouseButtonPress,QtCore.QEvent.MouseMove,QtCore.QEvent.MouseButtonRelease):return False
        point=self.owner.mapFromGlobal(event.globalPosition().toPoint())
        if kind==QtCore.QEvent.MouseMove and self.drag and self.drag[0]=='resize':
            self._resize_fallback(event.globalPosition().toPoint());return True
        if kind==QtCore.QEvent.MouseButtonRelease and self.drag and self.drag[0]=='resize':
            self.drag=None;self.owner.unsetCursor();return True
        # Return scrollbar gestures to their widget instead of treating them as window resize.
        if isinstance(obj,QtWidgets.QAbstractSlider):
            if kind==QtCore.QEvent.MouseMove:self.owner.unsetCursor()
            return False
        edge=self.edges(point)
        if kind==QtCore.QEvent.MouseMove and not self.drag:
            horizontal=edge&(QtCore.Qt.LeftEdge|QtCore.Qt.RightEdge)
            vertical=edge&(QtCore.Qt.TopEdge|QtCore.Qt.BottomEdge)
            if horizontal and vertical:
                backward=bool(edge&QtCore.Qt.TopEdge)==bool(edge&QtCore.Qt.LeftEdge)
                self.owner.setCursor(QtCore.Qt.SizeFDiagCursor if backward else QtCore.Qt.SizeBDiagCursor)
            elif horizontal:self.owner.setCursor(QtCore.Qt.SizeHorCursor)
            elif vertical:self.owner.setCursor(QtCore.Qt.SizeVerCursor)
            else:self.owner.unsetCursor()
        if kind==QtCore.QEvent.MouseButtonPress and event.button()==QtCore.Qt.LeftButton and edge:
            handle=self.owner.windowHandle()
            if not handle or not handle.startSystemResize(edge):
                self.drag=('resize',event.globalPosition().toPoint(),self.owner.geometry(),edge)
            return True
        return False

    def _resize_fallback(self,point):
        """Use press-time geometry for fallback resize and enforce minimum dimensions."""
        _,start,original,edge=self.drag;delta=point-start;rect=QtCore.QRect(original)
        if edge&QtCore.Qt.LeftEdge:rect.setLeft(min(original.left()+delta.x(),original.right()-self.owner.minimumWidth()+1))
        if edge&QtCore.Qt.RightEdge:rect.setRight(max(original.right()+delta.x(),original.left()+self.owner.minimumWidth()-1))
        if edge&QtCore.Qt.TopEdge:rect.setTop(min(original.top()+delta.y(),original.bottom()-self.owner.minimumHeight()+1))
        if edge&QtCore.Qt.BottomEdge:rect.setBottom(max(original.bottom()+delta.y(),original.top()+self.owner.minimumHeight()-1))
        self.owner.setGeometry(rect)

    def mousePressEvent(self,event):
        """Drag blank titlebar space while buttons retain independent native behavior."""
        if event.button()==QtCore.Qt.LeftButton and not self.owner.isMaximized():
            handle=self.owner.windowHandle()
            if not handle or not handle.startSystemMove():
                self.drag=('move',event.globalPosition().toPoint()-self.owner.frameGeometry().topLeft())
            event.accept()
        else:super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        """Fallback only when native window movement is unavailable; chart drags never enter here."""
        if self.drag and self.drag[0]=='move' and event.buttons()&QtCore.Qt.LeftButton:
            self.owner.move(event.globalPosition().toPoint()-self.drag[1]);event.accept()
        else:super().mouseMoveEvent(event)

    def mouseReleaseEvent(self,event):
        """End fallback movement so subsequent hover cannot move the window."""
        if self.drag and self.drag[0]=='move':self.drag=None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self,event):
        """Toggle maximize/restore on titlebar double-click without changing acquisition."""
        if event.button()==QtCore.Qt.LeftButton:self.toggle_maximize();event.accept()
        else:super().mouseDoubleClickEvent(event)

class CollapsibleSection(QtWidgets.QWidget):
    """Collapse right-panel groups independently without changing parameters or device state."""
    def __init__(self, title, content, expanded=True, parent=None):
        super().__init__(parent)
        self.content=content
        self.header=QtWidgets.QToolButton(self)
        self.header.setText(title);self.header.setCheckable(True)
        self.header.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.header.setSizePolicy(QtWidgets.QSizePolicy.Expanding,QtWidgets.QSizePolicy.Fixed)
        self.header.setMinimumHeight(34)
        self.header.setStyleSheet('QToolButton{background:transparent;border:0;border-radius:5px;'
                                 'padding:6px;text-align:left;color:#9caebc;} '
                                 'QToolButton:hover{background:#24313b;}')
        if isinstance(content,QtWidgets.QGroupBox):
            content.setTitle('')
            content.setStyleSheet('QGroupBox{margin-top:0;padding:8px 8px 10px;}')
        layout=QtWidgets.QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(1)
        layout.addWidget(self.header);layout.addWidget(content)
        self.header.toggled.connect(self._toggle)
        self.set_expanded(expanded)

    def set_expanded(self, expanded):
        """Synchronize action, arrow and content visibility; expand to keep stop accessible on start."""
        self.header.setChecked(expanded)
        self._toggle(expanded)

    def _toggle(self, expanded):
        self.content.setVisible(expanded)
        self.header.setArrowType(QtCore.Qt.DownArrow if expanded else QtCore.Qt.RightArrow)


# End of file: window_chrome.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
