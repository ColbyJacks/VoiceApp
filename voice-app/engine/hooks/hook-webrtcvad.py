# The stock hook copies metadata for "webrtcvad", but Voice App installs the
# "webrtcvad-wheels" distribution, so the stock hook fails to import.
from PyInstaller.utils.hooks import copy_metadata

datas = copy_metadata("webrtcvad-wheels")
