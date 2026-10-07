"""배포 번들 진입점.

- 기본: GUI 실행. Finder에서 파일을 열면 인자로 들어와 큐에 적재된다.
- `--cli <옵션…>`: CLI 모드. 번들 하나로 Quick Action·스크립트 연동까지 커버한다.

  예) LectureScribe.app/Contents/MacOS/LectureScribe --cli "강의.m4a" --json
"""

from __future__ import annotations

import multiprocessing
import sys


def main() -> int:
    multiprocessing.freeze_support()
    args = sys.argv[1:]
    if args and args[0] == "--cli":
        from lecture_scribe.cli import main as cli_main

        return cli_main(args[1:])
    from lecture_scribe.gui.app import main as gui_main

    return gui_main(args)


if __name__ == "__main__":
    sys.exit(main())
