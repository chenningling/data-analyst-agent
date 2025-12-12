import io
import sys
import textwrap

def run_python_code(code: str) -> dict:
    """
    在当前进程里执行一段 Python 代码，返回 stdout 和异常信息。
    这里为了简单起见，没有安全限制，仅用于示例。
    """
    old_stdout = sys.stdout
    stdout_buffer = io.StringIO()
    sys.stdout = stdout_buffer

    error = None
    try:
        exec(textwrap.dedent(code), {})
    except Exception as e:
        error = repr(e)
    finally:
        sys.stdout = old_stdout

    return {
        "stdout": stdout_buffer.getvalue(),
        "error": error,
    }