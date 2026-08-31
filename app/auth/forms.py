from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Length


class LoginForm(FlaskForm):
    username = StringField(
        "Username",
        validators=[DataRequired(), Length(min=1, max=80)],
        render_kw={"autocomplete": "username"},
    )
    password = PasswordField(
        "Password",
        validators=[DataRequired(), Length(max=256)],
        render_kw={"autocomplete": "current-password"},
    )
    remember = BooleanField("Keep me signed in on this device")
    submit = SubmitField("Sign in")


class LogoutForm(FlaskForm):
    submit = SubmitField("Sign out")


class WorkspaceIntegrationsForm(FlaskForm):
    youtube_api_key = PasswordField(
        "YouTube API key",
        validators=[Length(max=256)],
        render_kw={"autocomplete": "off"},
    )
    youtube_playlist_id = StringField(
        "YouTube playlist ID",
        validators=[Length(max=160)],
        render_kw={"autocomplete": "off"},
    )
    notion_token = PasswordField(
        "Notion integration token",
        validators=[Length(max=512)],
        render_kw={"autocomplete": "off"},
    )
    notion_database_id = StringField(
        "Movies Notion database or data source ID",
        validators=[Length(max=160)],
        render_kw={"autocomplete": "off"},
    )
    book_notion_database_id = StringField(
        "Books Notion database or data source ID",
        validators=[Length(max=160)],
        render_kw={"autocomplete": "off"},
    )
    submit = SubmitField("Save private integrations")
