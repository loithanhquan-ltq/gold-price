from fastapi import Header, HTTPException, status
from backend.config import API_TOKEN


def require_token(x_api_token: str = Header(default="")):
    if not API_TOKEN or x_api_token != API_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API token")
