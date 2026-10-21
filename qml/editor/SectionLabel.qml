import QtQuick
import "."

Text {
    textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
    color: Style.inkSoft
    font.pixelSize: 11
    font.weight: Font.DemiBold
    font.capitalization: Font.AllUppercase
    font.letterSpacing: 0.6
}
