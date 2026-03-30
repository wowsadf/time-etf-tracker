class DataNotReadyError(Exception):
    """다운로드된 파일은 정상 형식이지만 실제 데이터가 아직 비어 있는 상태"""
    pass