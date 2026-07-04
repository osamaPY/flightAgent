import requests
import hmac
import hashlib
import base64
import time
import uuid
from typing import List, Optional, Dict, Any
from src.core.logger import log_info, log_error

class RoutestackClient:
    def __init__(self, api_key: str = None, api_secret: str = None, base_url: str = None):
        if api_key is None or api_secret is None or base_url is None:
            from src.core.config import Config
            api_key = api_key or Config.ROUTESTACK_API_KEY
            api_secret = api_secret or Config.ROUTESTACK_API_SECRET
            base_url = base_url or Config.ROUTESTACK_BASE_URL
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url
        self._token = None
        self._token_expiry = 0

    def _generate_token(self) -> bool:
        if not self.api_key or not self.api_secret or not self.base_url:
            log_info("Routestack hotel lookup skipped: missing credentials.")
            return False

        ts = int(time.time())
        nonce = str(uuid.uuid4())
        message = f"{self.api_key}:{ts}:{nonce}"
        
        signature = hmac.new(self.api_secret.encode(), message.encode(), hashlib.sha256).digest()
        hmac_str = base64.urlsafe_b64encode(signature).decode().rstrip('=')
        
        payload = {
            "apiKey": self.api_key,
            "hmac": hmac_str,
            "timestamp": ts,
            "nonce": nonce
        }
        
        try:
            response = requests.post(f"{self.base_url}/mcp/auth/partner-token", json=payload, timeout=10)
            if response.status_code == 200:
                data = response.json()
                self._token = data.get('token')
                # expires in 24h, but we'll refresh if needed
                self._token_expiry = time.time() + 86400 - 300 
                return True
            else:
                log_error(f"Routestack Auth Failed: {response.status_code} {response.text}")
                return False
        except Exception as e:
            log_error(f"Routestack Auth Exception: {e}")
            return False

    def get_headers(self) -> Dict[str, str]:
        if not self._token or time.time() > self._token_expiry:
            if not self._generate_token():
                return {}
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json"
        }

    def search_hotels(self, city: str, check_in: str, check_out: str) -> List[Dict[str, Any]]:
        # First resolve city to destinationId
        headers = self.get_headers()
        if not headers: return []
        
        try:
            # Resolve destination
            dest_res = requests.post(
                f"{self.base_url}/mcp/hotel/search-destinations",
                headers=headers,
                json={"query": city, "type": "DESTINATION"},
                timeout=10
            )
            dest_data = dest_res.json()
            if not dest_data.get('success') or not dest_data.get('result'):
                return []
            
            dest = dest_data['result'][0]
            dest_id = dest.get('destinationId')
            lat = dest.get('lat')
            lng = dest.get('long')
            
            # Search hotels
            search_payload = {
                "destinationId": dest_id,
                "lat": lat,
                "long": lng,
                "checkIn": check_in,
                "checkOut": check_out,
                "rooms": [{"adults": 2, "children": []}],
                "currency": "EUR",
                "destinationType": dest.get('type', "CITY")
            }
            
            hotel_res = requests.post(
                f"{self.base_url}/mcp/hotel/search-hotels",
                headers=headers,
                json=search_payload,
                timeout=20
            )
            return hotel_res.json().get('result', [])
        except Exception as e:
            log_error(f"Routestack search failed: {e}")
            return []
