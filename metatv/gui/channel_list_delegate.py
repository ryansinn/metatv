"""Item delegate for the virtualized channel list.

The only thing this delegate adds over the default ``QStyledItemDelegate`` is
*colour* on the fixed playback-state separator glyph (·/▶/✓) that sits between the
leading icons/tags and the title.  The model already embeds that glyph in the plain
``DisplayRole`` text (so the SHAPE — which is what makes it colourblind-safe — is
always present); this delegate renders the row from ``CHANNEL_HTML_ROLE`` instead,
where the glyph is wrapped in a theme-token colour ``<span>``:

    - ▶  in-progress / resumable → ``COLOR_PLAYBACK_IN_PROGRESS`` (Resume orange)
    - ✓  watched                 → ``COLOR_PLAYBACK_WATCHED`` (success green)

All other text keeps the row's normal foreground (the dimmed watched brush when the
model returns one, the highlight colour when selected).  Colour is reinforcement
only — the delegate degrades gracefully to the plain ``DisplayRole`` text if the
HTML role is ever empty.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import (
    QAbstractTextDocumentLayout,
    QBrush,
    QPalette,
    QTextDocument,
    QTextOption,
)
from PyQt6.QtWidgets import (
    QApplication,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)

from metatv.gui.channel_list_model import CHANNEL_HTML_ROLE


class ChannelRowDelegate(QStyledItemDelegate):
    """Paints channel rows as rich text so the playback indicator can be coloured."""

    def paint(self, painter, option, index) -> None:  # noqa: N802
        html = index.data(CHANNEL_HTML_ROLE)
        if not html:
            # No HTML (e.g. invalid index) — fall back to the default text render.
            super().paint(painter, option, index)
            return

        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        style = opt.widget.style() if opt.widget is not None else QApplication.style()

        # Default colour for all NON-glyph text: highlight when selected, else the
        # row's ForegroundRole brush (dimmed for watched rows) or the palette text.
        if opt.state & QStyle.StateFlag.State_Selected:
            default_color = opt.palette.color(QPalette.ColorRole.HighlightedText)
        else:
            fg = index.data(Qt.ItemDataRole.ForegroundRole)
            default_color = (
                fg.color()
                if isinstance(fg, QBrush)
                else opt.palette.color(QPalette.ColorRole.Text)
            )

        doc = QTextDocument()
        doc.setDocumentMargin(0)
        doc.setDefaultFont(opt.font)
        text_option = QTextOption()
        text_option.setWrapMode(QTextOption.WrapMode.NoWrap)
        doc.setDefaultTextOption(text_option)
        doc.setHtml(f'<span style="color:{default_color.name()}">{html}</span>')

        # Draw the row chrome (background, selection, hover, focus) with NO text —
        # the rich text is painted by hand below.
        opt.text = ""
        style.drawControl(
            QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget
        )

        text_rect = style.subElementRect(
            QStyle.SubElement.SE_ItemViewItemText, opt, opt.widget
        )
        painter.save()
        painter.setClipRect(text_rect)
        # Vertically centre the single line within the row.
        y = text_rect.y() + max(0.0, (text_rect.height() - doc.size().height()) / 2)
        painter.translate(text_rect.x(), y)
        ctx = QAbstractTextDocumentLayout.PaintContext()
        ctx.palette = opt.palette
        doc.documentLayout().draw(painter, ctx)
        painter.restore()
