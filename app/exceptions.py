class DataNotReadyError(Exception):
    """다운로드된 파일은 정상 형식이지만 실제 데이터가 아직 비어 있는 상태"""
    pass


class StateCorruptionError(RuntimeError):
    """상태 파일이 손상되었거나 예상한 JSON 구조가 아닌 상태"""

    pass
