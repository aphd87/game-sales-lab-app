"""Game Sales Lab: classroom dashboard on the video game business, built on VGChartz unit sales. Companion to the
Behind the Box Office Lab and built on the same code: one long page, the same design system, the same shared chart
cache (every chart is built once per distinct set of inputs and shared by all sessions, see show_chart) and the same
hover definitions.

Everything is precomputed by build_data.py into data/ (merged VGChartz games, prediction-model scores, the pitch
grid), so a click only filters a ~19,000-row table. Nothing is fitted while students use the app.
APP_PASSWORD, if set as a secret or environment variable, gates the app; locally there is no password.
"""
