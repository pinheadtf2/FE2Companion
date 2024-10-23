Set "VIRTUAL_ENV=.venv"

If Not Exist "%VIRTUAL_ENV%\Scripts\activate.bat" (
    python -m venv %VIRTUAL_ENV%
    Call "%VIRTUAL_ENV%\Scripts\activate.bat"
    pip install -r requirements.txt
)

If Not Exist "%VIRTUAL_ENV%\Scripts\activate.bat" Exit /B 1
Call "%VIRTUAL_ENV%\Scripts\activate.bat"
python main.py

PAUSE