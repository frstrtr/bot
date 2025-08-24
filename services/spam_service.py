"""Modern spam detection service with async support."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

import aiohttp
from aiogram import types

from utils.database import DatabaseManager, SpamRecord
from utils.logger import get_logger, log_async_function_call

logger = get_logger(__name__)


class SpamPattern:
    """Spam pattern definition."""
    
    def __init__(
        self,
        name: str,
        pattern: str,
        confidence: float,
        is_regex: bool = False,
        case_sensitive: bool = False
    ):
        self.name = name
        self.pattern = pattern
        self.confidence = confidence
        self.is_regex = is_regex
        self.case_sensitive = case_sensitive
        
        if is_regex:
            flags = 0 if case_sensitive else re.IGNORECASE
            self.compiled_pattern = re.compile(pattern, flags)
        else:
            self.compiled_pattern = None


class SpamDetectionResult:
    """Result of spam detection analysis."""
    
    def __init__(
        self,
        is_spam: bool,
        confidence: float,
        detected_patterns: List[str],
        spam_type: str,
        content_hash: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        self.is_spam = is_spam
        self.confidence = confidence
        self.detected_patterns = detected_patterns
        self.spam_type = spam_type
        self.content_hash = content_hash
        self.details = details or {}


class SpamService:
    """Advanced spam detection and management service."""
    
    def __init__(self, settings, db_manager: DatabaseManager):
        self.settings = settings
        self.db = db_manager
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Spam patterns
        self.spam_patterns: List[SpamPattern] = []
        self.url_patterns: List[SpamPattern] = []
        self.suspicious_domains: Set[str] = set()
        
        # Rate limiting
        self.user_message_count: Dict[int, List[datetime]] = {}
        self.rate_limit_window = 60  # seconds
        self.rate_limit_threshold = 10  # messages per window
        
        # Content hashing for duplicate detection
        self.recent_content_hashes: Dict[str, List[Tuple[int, datetime]]] = {}
        self.content_hash_window = 300  # 5 minutes
        
        # API clients
        self.api_timeout = settings.API_TIMEOUT
        
        self._initialize_patterns()
    
    async def initialize(self) -> None:
        """Initialize the spam service."""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.api_timeout)
        )
        await self._load_spam_dictionary()
        await self._load_suspicious_domains()
        logger.info("Spam service initialized")
    
    async def close(self) -> None:
        """Close the spam service and cleanup resources."""
        if self.session:
            await self.session.close()
        logger.info("Spam service closed")
    
    def _initialize_patterns(self) -> None:
        """Initialize built-in spam patterns."""
        
        # URL and link patterns
        self.url_patterns = [
            SpamPattern(
                "http_url",
                r"https?://[^\s]+",
                0.6,
                is_regex=True
            ),
            SpamPattern(
                "text_link",
                r"\[.+\]\(.+\)",
                0.7,
                is_regex=True
            ),
            SpamPattern(
                "telegram_link", 
                r"t\.me/[a-zA-Z0-9_]+",
                0.8,
                is_regex=True
            ),
            SpamPattern(
                "suspicious_tld",
                r"\.(?:tk|ml|ga|cf|pw|click|download)\b",
                0.9,
                is_regex=True
            )
        ]
        
        # Contact patterns
        self.spam_patterns = [
            SpamPattern(
                "phone_number",
                r"[\+]?[1-9]?[0-9]{7,14}",
                0.5,
                is_regex=True
            ),
            SpamPattern(
                "email",
                r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
                0.6,
                is_regex=True
            ),
            SpamPattern(
                "crypto_address",
                r"\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b",
                0.8,
                is_regex=True
            )
        ]
    
    async def _load_spam_dictionary(self) -> None:
        """Load spam dictionary from file."""
        try:
            with open(self.settings.SPAM_DICT_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    pattern = line.strip()
                    if pattern and not pattern.startswith('#'):
                        self.spam_patterns.append(
                            SpamPattern(
                                f"dict_{len(self.spam_patterns)}",
                                pattern,
                                0.7,
                                case_sensitive=False
                            )
                        )
            logger.info(f"Loaded {len(self.spam_patterns)} spam patterns")
        except FileNotFoundError:
            logger.warning(f"Spam dictionary file {self.settings.SPAM_DICT_FILE} not found")
        except Exception as e:
            logger.error(f"Error loading spam dictionary: {e}")
    
    async def _load_suspicious_domains(self) -> None:
        """Load suspicious domains from external sources."""
        # This would typically load from a file or API
        suspicious_domains = [
            "bit.ly", "tinyurl.com", "short.link", "rebrand.ly",
            "spam-site.com", "malware-host.net"
        ]
        self.suspicious_domains.update(suspicious_domains)
        logger.info(f"Loaded {len(self.suspicious_domains)} suspicious domains")
    
    @log_async_function_call
    async def analyze_message(self, message: types.Message) -> SpamDetectionResult:
        """Analyze message for spam content."""
        
        # Extract content for analysis
        content = self._extract_message_content(message)
        content_hash = self._generate_content_hash(content)
        
        detected_patterns = []
        max_confidence = 0.0
        spam_types = []
        
        # Check for rate limiting
        rate_limit_result = await self._check_rate_limiting(message.from_user.id)
        if rate_limit_result.is_spam:
            return rate_limit_result
        
        # Check for duplicate content
        duplicate_result = await self._check_duplicate_content(
            content_hash, message.from_user.id
        )
        if duplicate_result.is_spam:
            return duplicate_result
        
        # Analyze text content
        if content.get('text'):
            text_result = await self._analyze_text_content(content['text'])
            if text_result.is_spam:
                detected_patterns.extend(text_result.detected_patterns)
                max_confidence = max(max_confidence, text_result.confidence)
                spam_types.append(text_result.spam_type)
        
        # Analyze entities (URLs, mentions, etc.)
        if content.get('entities'):
            entity_result = await self._analyze_entities(content['entities'])
            if entity_result.is_spam:
                detected_patterns.extend(entity_result.detected_patterns)
                max_confidence = max(max_confidence, entity_result.confidence)
                spam_types.append(entity_result.spam_type)
        
        # Analyze forwarded content
        if content.get('forward_info'):
            forward_result = await self._analyze_forward(content['forward_info'])
            if forward_result.is_spam:
                detected_patterns.extend(forward_result.detected_patterns)
                max_confidence = max(max_confidence, forward_result.confidence)
                spam_types.append(forward_result.spam_type)
        
        # Check external APIs
        if max_confidence > 0.3:  # Only check APIs for suspicious content
            api_result = await self._check_external_apis(message)
            if api_result and api_result.is_spam:
                detected_patterns.extend(api_result.detected_patterns)
                max_confidence = max(max_confidence, api_result.confidence)
                spam_types.append(api_result.spam_type)
        
        # Determine final result
        is_spam = max_confidence >= 0.7
        final_spam_type = spam_types[0] if spam_types else "unknown"
        
        result = SpamDetectionResult(
            is_spam=is_spam,
            confidence=max_confidence,
            detected_patterns=detected_patterns,
            spam_type=final_spam_type,
            content_hash=content_hash,
            details={
                "user_id": message.from_user.id,
                "chat_id": message.chat.id,
                "message_id": message.message_id,
                "spam_types": spam_types
            }
        )
        
        # Record detection if spam
        if is_spam:
            await self._record_spam_detection(message, result)
        
        return result
    
    def _extract_message_content(self, message: types.Message) -> Dict[str, Any]:
        """Extract content from message for analysis."""
        content = {
            'text': message.text or message.caption or '',
            'entities': [],
            'forward_info': None
        }
        
        # Extract entities
        if message.entities:
            for entity in message.entities:
                content['entities'].append({
                    'type': entity.type,
                    'offset': entity.offset,
                    'length': entity.length,
                    'url': getattr(entity, 'url', None),
                    'user': getattr(entity, 'user', None)
                })
        
        # Extract forward information
        if message.forward_from or message.forward_from_chat:
            content['forward_info'] = {
                'from_user': message.forward_from.id if message.forward_from else None,
                'from_chat': message.forward_from_chat.id if message.forward_from_chat else None,
                'from_message_id': getattr(message, 'forward_from_message_id', None)
            }
        
        return content
    
    def _generate_content_hash(self, content: Dict[str, Any]) -> str:
        """Generate hash for content deduplication."""
        text = content.get('text', '')
        # Normalize text (remove whitespace, convert to lowercase)
        normalized = re.sub(r'\s+', ' ', text.lower().strip())
        return hashlib.md5(normalized.encode()).hexdigest()
    
    async def _check_rate_limiting(self, user_id: int) -> SpamDetectionResult:
        """Check if user is sending messages too frequently."""
        now = datetime.now()
        
        if user_id not in self.user_message_count:
            self.user_message_count[user_id] = []
        
        # Clean old timestamps
        cutoff = now - timedelta(seconds=self.rate_limit_window)
        self.user_message_count[user_id] = [
            ts for ts in self.user_message_count[user_id] if ts > cutoff
        ]
        
        # Add current timestamp
        self.user_message_count[user_id].append(now)
        
        # Check if rate limit exceeded
        message_count = len(self.user_message_count[user_id])
        if message_count > self.rate_limit_threshold:
            return SpamDetectionResult(
                is_spam=True,
                confidence=0.9,
                detected_patterns=['rate_limit'],
                spam_type='rate_limit',
                details={'message_count': message_count, 'window': self.rate_limit_window}
            )
        
        return SpamDetectionResult(
            is_spam=False,
            confidence=0.0,
            detected_patterns=[],
            spam_type='none'
        )
    
    async def _check_duplicate_content(
        self, 
        content_hash: str, 
        user_id: int
    ) -> SpamDetectionResult:
        """Check for duplicate content across multiple users."""
        now = datetime.now()
        
        if content_hash not in self.recent_content_hashes:
            self.recent_content_hashes[content_hash] = []
        
        # Clean old entries
        cutoff = now - timedelta(seconds=self.content_hash_window)
        self.recent_content_hashes[content_hash] = [
            (uid, ts) for uid, ts in self.recent_content_hashes[content_hash]
            if ts > cutoff
        ]
        
        # Check for duplicates from different users
        unique_users = set(uid for uid, _ in self.recent_content_hashes[content_hash])
        
        # Add current user
        self.recent_content_hashes[content_hash].append((user_id, now))
        
        if len(unique_users) >= 3:  # Same content from 3+ users
            return SpamDetectionResult(
                is_spam=True,
                confidence=0.8,
                detected_patterns=['duplicate_content'],
                spam_type='duplicate',
                content_hash=content_hash,
                details={'duplicate_users': len(unique_users)}
            )
        
        return SpamDetectionResult(
            is_spam=False,
            confidence=0.0,
            detected_patterns=[],
            spam_type='none'
        )
    
    async def _analyze_text_content(self, text: str) -> SpamDetectionResult:
        """Analyze text content for spam patterns."""
        detected_patterns = []
        max_confidence = 0.0
        
        for pattern in self.spam_patterns:
            if pattern.compiled_pattern:
                if pattern.compiled_pattern.search(text):
                    detected_patterns.append(pattern.name)
                    max_confidence = max(max_confidence, pattern.confidence)
            else:
                search_text = text if pattern.case_sensitive else text.lower()
                search_pattern = pattern.pattern if pattern.case_sensitive else pattern.pattern.lower()
                
                if search_pattern in search_text:
                    detected_patterns.append(pattern.name)
                    max_confidence = max(max_confidence, pattern.confidence)
        
        return SpamDetectionResult(
            is_spam=max_confidence >= 0.7,
            confidence=max_confidence,
            detected_patterns=detected_patterns,
            spam_type='text_spam'
        )
    
    async def _analyze_entities(self, entities: List[Dict[str, Any]]) -> SpamDetectionResult:
        """Analyze message entities for spam indicators."""
        detected_patterns = []
        max_confidence = 0.0
        
        # Get spam triggers from settings
        spam_triggers = getattr(self.settings, 'SPAM_TRIGGERS', [
            'url', 'text_link', 'email', 'phone_number', 'hashtag', 
            'mention', 'cashtag', 'bot_command', 'story'
        ])
        
        for entity in entities:
            entity_type = entity.get('type')
            
            # Check if this entity type is in our spam triggers (simple like aiogram2)
            if entity_type in spam_triggers:
                detected_patterns.append(f'entity_{entity_type}')
                
                # Set confidence based on entity type (optimized from aiogram2)
                if entity_type in ['url', 'text_link']:
                    # URLs are highly suspicious
                    confidence = 0.8
                    # If we have the actual URL, analyze it further
                    url = entity.get('url', '')
                    if url:
                        url_result = await self._analyze_url(url)
                        if url_result.is_spam:
                            detected_patterns.extend(url_result.detected_patterns)
                            confidence = max(confidence, url_result.confidence)
                    max_confidence = max(max_confidence, confidence)
                    
                elif entity_type in ['email', 'phone_number']:
                    # Contact info is moderately suspicious
                    max_confidence = max(max_confidence, 0.7)
                    
                elif entity_type == 'story':
                    # Stories are moderately suspicious (new trigger)
                    max_confidence = max(max_confidence, 0.6)
                    
                elif entity_type in ['mention', 'hashtag', 'cashtag']:
                    # Social media entities are less suspicious
                    max_confidence = max(max_confidence, 0.5)
                    
                elif entity_type == 'bot_command':
                    # Bot commands are least suspicious
                    max_confidence = max(max_confidence, 0.3)
                    
                else:
                    # Default for any other configured trigger types
                    max_confidence = max(max_confidence, 0.5)
        
        return SpamDetectionResult(
            is_spam=max_confidence >= 0.7,
            confidence=max_confidence,
            detected_patterns=detected_patterns,
            spam_type='entity_spam'
        )
    
    async def _analyze_url(self, url: str) -> SpamDetectionResult:
        """Analyze URL for spam indicators."""
        detected_patterns = []
        confidence = 0.0
        
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            
            # Check suspicious domains
            if domain in self.suspicious_domains:
                detected_patterns.append('suspicious_domain')
                confidence = max(confidence, 0.8)
            
            # Check URL patterns
            for pattern in self.url_patterns:
                if pattern.compiled_pattern and pattern.compiled_pattern.search(url):
                    detected_patterns.append(pattern.name)
                    confidence = max(confidence, pattern.confidence)
            
            # Check for URL shorteners
            shortener_domains = ['bit.ly', 'tinyurl.com', 'short.link', 't.co']
            if any(domain.endswith(d) for d in shortener_domains):
                detected_patterns.append('url_shortener')
                confidence = max(confidence, 0.5)
        
        except Exception as e:
            logger.error(f"Error analyzing URL {url}: {e}")
        
        return SpamDetectionResult(
            is_spam=confidence >= 0.7,
            confidence=confidence,
            detected_patterns=detected_patterns,
            spam_type='url_spam'
        )
    
    async def _analyze_forward(self, forward_info: Dict[str, Any]) -> SpamDetectionResult:
        """Analyze forwarded message for spam indicators."""
        detected_patterns = []
        confidence = 0.0
        
        # Check if forwarded from known spam sources
        from_chat = forward_info.get('from_chat')
        if from_chat and from_chat in self.settings.get('SPAM_CHAT_IDS', []):
            detected_patterns.append('spam_forward_source')
            confidence = 0.8
        
        # Check if forwarded from suspicious channels
        # This would be implemented based on your specific requirements
        
        return SpamDetectionResult(
            is_spam=confidence >= 0.7,
            confidence=confidence,
            detected_patterns=detected_patterns,
            spam_type='forward_spam'
        )
    
    async def _check_external_apis(self, message: types.Message) -> Optional[SpamDetectionResult]:
        """Check external spam detection APIs."""
        if not self.session:
            return None
        
        try:
            # Check local spam API if available
            local_result = await self._check_local_spam_api(message)
            if local_result and local_result.is_spam:
                return local_result
            
            # Check CAS API for user
            cas_result = await self._check_cas_api(message.from_user.id)
            if cas_result and cas_result.is_spam:
                return cas_result
            
        except Exception as e:
            logger.error(f"Error checking external APIs: {e}")
        
        return None
    
    async def _check_local_spam_api(self, message: types.Message) -> Optional[SpamDetectionResult]:
        """Check local spam detection API."""
        try:
            url = f"{self.settings.LOCAL_SPAM_API_URL}/check"
            payload = {
                'text': message.text or message.caption or '',
                'user_id': message.from_user.id
            }
            
            async with self.session.post(url, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get('is_spam'):
                        return SpamDetectionResult(
                            is_spam=True,
                            confidence=data.get('confidence', 0.8),
                            detected_patterns=['local_api'],
                            spam_type='api_detected'
                        )
        except Exception as e:
            logger.error(f"Local spam API error: {e}")
        
        return None
    
    async def _check_cas_api(self, user_id: int) -> Optional[SpamDetectionResult]:
        """Check CAS (Combot Anti-Spam) API."""
        try:
            url = f"{self.settings.CAS_API_URL}/check"
            params = {'user_id': user_id}
            
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get('ok') and data.get('result', {}).get('offenses', 0) > 0:
                        return SpamDetectionResult(
                            is_spam=True,
                            confidence=0.9,
                            detected_patterns=['cas_ban'],
                            spam_type='cas_detected'
                        )
        except Exception as e:
            logger.error(f"CAS API error: {e}")
        
        return None
    
    async def _record_spam_detection(
        self, 
        message: types.Message, 
        result: SpamDetectionResult
    ) -> None:
        """Record spam detection in database."""
        try:
            spam_record = SpamRecord(
                user_id=message.from_user.id,
                message_id=message.message_id,
                chat_id=message.chat.id,
                detected_at=datetime.now(),
                spam_type=result.spam_type,
                confidence=result.confidence,
                content_hash=result.content_hash
            )
            
            await self.db.record_spam_detection(spam_record)
            
        except Exception as e:
            logger.error(f"Error recording spam detection: {e}")
    
    async def get_user_spam_history(
        self, 
        user_id: int, 
        hours: int = 24
    ) -> List[SpamRecord]:
        """Get user's spam detection history."""
        return await self.db.get_spam_history(user_id, hours)
    
    def has_spam_entities(self, message: types.Message) -> Optional[str]:
        """
        Check if the message contains spam entities (simplified version like aiogram2).
        
        Args:
            message: The message to check.
            
        Returns:
            str: The entity type that triggered spam detection, or None if no spam entities found.
        """
        # Get spam triggers from settings
        spam_triggers = getattr(self.settings, 'SPAM_TRIGGERS', [
            'url', 'text_link', 'email', 'phone_number', 'hashtag', 
            'mention', 'cashtag', 'bot_command', 'story'
        ])
        
        if message.entities:
            for entity in message.entities:
                if entity.type in spam_triggers:
                    # Spam detected - return the entity type that triggered it
                    return entity.type
        return None
    
    async def update_spam_patterns(self, patterns: List[Dict[str, Any]]) -> None:
        """Update spam patterns dynamically."""
        new_patterns = []
        for pattern_data in patterns:
            pattern = SpamPattern(
                name=pattern_data['name'],
                pattern=pattern_data['pattern'],
                confidence=pattern_data['confidence'],
                is_regex=pattern_data.get('is_regex', False),
                case_sensitive=pattern_data.get('case_sensitive', False)
            )
            new_patterns.append(pattern)
        
        self.spam_patterns.extend(new_patterns)
        logger.info(f"Added {len(new_patterns)} new spam patterns")
    
    async def cleanup_old_data(self) -> None:
        """Clean up old tracking data."""
        now = datetime.now()
        
        # Clean rate limiting data
        for user_id, timestamps in list(self.user_message_count.items()):
            cutoff = now - timedelta(seconds=self.rate_limit_window)
            cleaned = [ts for ts in timestamps if ts > cutoff]
            if cleaned:
                self.user_message_count[user_id] = cleaned
            else:
                del self.user_message_count[user_id]
        
        # Clean content hash data
        for hash_key, entries in list(self.recent_content_hashes.items()):
            cutoff = now - timedelta(seconds=self.content_hash_window)
            cleaned = [(uid, ts) for uid, ts in entries if ts > cutoff]
            if cleaned:
                self.recent_content_hashes[hash_key] = cleaned
            else:
                del self.recent_content_hashes[hash_key]
