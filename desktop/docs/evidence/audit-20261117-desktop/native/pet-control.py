import socket,sys
from pathlib import Path
root=Path('/workspace/scratch/c0f3ec78c621/validation/native-audit-20261117/profile-d/client')
action=sys.argv[1]
assert action in ('measure_animation','inspect','show','hide','center','anchor:TOP_LEFT','anchor:TOP_RIGHT','anchor:LEFT_EDGE','anchor:RIGHT_EDGE','anchor:BOTTOM_LEFT','anchor:BOTTOM_RIGHT')
with socket.socket(socket.AF_UNIX) as client:
    client.settimeout(3)
    client.connect(str(root/'pet-control.sock'))
    client.sendall(action.encode())
print('sent',action)
