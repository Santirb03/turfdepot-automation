# Fonts used only by pytest in CI

Carlito Regular and Bold are distributed under the SIL Open Font License 1.1;
see OFL.txt. Downloaded from the official project:
https://github.com/googlefonts/carlito/tree/3a810cab78ebd6e2e4eed42af9e8453c4f9b850a

Original paths: fonts/ttf/Carlito-Regular.ttf, fonts/ttf/Carlito-Bold.ttf.
The files are unmodified. They are registered under the renderer's logical font
names only when pytest receives `--pdf-test-fonts=carlito`. There is no production
fallback: the application still requires the privately supplied Calibri fonts.

These tests check PDF content, calculations and images. They do not certify the
exact appearance of the approved Calibri design; that requires local rendering.
