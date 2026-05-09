"""Factory for creating EmailParsers."""

import logging
from .base import BaseEmailParser, logger

class ParserFactory:
    """Factory to create the appropriate EmailParser strategy."""

    @staticmethod
    def create(extract_format: str, filter_name: str = "") -> BaseEmailParser:
        """Create a parser based on format and filter name.
        
        The extract_format determines the general parsing strategy, while 
        filter_name allows for source-specific specializations.
        """
        
        # 1. Medium-specific format
        if extract_format == "medium":
            from .parse_medium import MediumParser
            return MediumParser()
        # 2. 'Source Link' format
        elif extract_format == "source_link":
            from .source_link import SourceLinkParser
            return SourceLinkParser()
        
        # 3. 'BestBlogs' format
        elif extract_format == "bestblogs":
            from .parse_bestblogs import BestBlogsParser
            return BestBlogsParser()

        # 4. 'Name ( URL )' format
        elif extract_format == "name_url":
            # Fallback for old configs where name='medium' but format='name_url'
            if filter_name.lower() == "medium":
                from .parse_medium import MediumParser
                return MediumParser()
            from .name_url import NameUrlParser
            return NameUrlParser()
            
        # 5. 'All URLs' format
        elif extract_format == "all_urls":
            from .all_urls import AllUrlsParser
            return AllUrlsParser()            
            
        # Fallback logic
        else:
            if extract_format:
                logger.warning(
                    "Unknown extract_format '%s', falling back to 'name_url'",
                    extract_format
                )
            
            from .name_url import NameUrlParser
            return NameUrlParser()


class EmailParser:
    """Factory alias for backwards compatibility and convenience."""

    def __new__(cls, extract_format: str = "name_url", filter_name: str = ""):
        return ParserFactory.create(extract_format, filter_name)
