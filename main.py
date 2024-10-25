import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import time
import random
import logging
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import os
import streamlit as st

USER_AGENTS = [
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.361675787110',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 11_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.5412.99 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.5361.172 Safari/537.36',
    'Mozilla/5.0 (X11; Linux i686) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.5388.177 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 11_14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.5397.215 Safari/537.36'
]

class CrawlerAgent:
    def __init__(self, url):
        self.url = self._normalize_url(url)
        self.headers = self._get_headers()
        self.session = requests.Session()
        self._setup_logging()
    
    def _setup_logging(self):
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)
    
    def _normalize_url(self, url):
        """Ensure URL has proper protocol and formatting"""
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        parsed = urlparse(url)
        return parsed.geturl()
    
    def _get_headers(self):
        """Generate realistic browser headers with random User-Agent"""
        return {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
        }
    
    def fetch_content(self, max_retries=3, delay=2):
        """Fetch content with retry logic and better error handling"""
        for attempt in range(max_retries):
            try:
                self.logger.info(f"Attempting to fetch {self.url} (Attempt {attempt + 1}/{max_retries})")
                
                # Add a delay between requests
                time.sleep(delay)
                
                # Rotate User-Agent for each attempt
                self.headers['User-Agent'] = random.choice(USER_AGENTS)
                
                response = self.session.get(
                    self.url,
                    headers=self.headers,
                    timeout=10,
                    allow_redirects=True
                )
                
                # Check for various status codes
                if response.status_code == 200:
                    return response.text
                elif response.status_code == 403:
                    self.logger.error("Access forbidden - site may have anti-bot protection")
                    return None
                elif response.status_code == 429:
                    wait_time = int(response.headers.get('Retry-After', delay * (attempt + 1)))
                    self.logger.warning(f"Rate limited - waiting {wait_time} seconds")
                    time.sleep(wait_time)
                    continue
                else:
                    self.logger.error(f"Failed to fetch content: HTTP {response.status_code}")
                    
            except requests.exceptions.SSLError:
                self.logger.warning("SSL Error - attempting without verification")
                try:
                    response = self.session.get(
                        self.url,
                        headers=self.headers,
                        verify=False,
                        timeout=10
                    )
                    if response.status_code == 200:
                        return response.text
                except Exception as e:
                    self.logger.error(f"Secondary request failed: {str(e)}")
                    
            except requests.exceptions.RequestException as e:
                self.logger.error(f"Request failed: {str(e)}")
                time.sleep(delay * (attempt + 1))
                
            except Exception as e:
                self.logger.error(f"Unexpected error: {str(e)}")
                return None
                
        self.logger.error(f"Failed to fetch content after {max_retries} attempts")
        return None

class ParserAgent:
    def __init__(self, html_content, url):
        self.html_content = html_content
        self.url = url
        self.soup = None
        self._setup_logging()
    
    def _setup_logging(self):
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)
    
    def parse(self):
        if not self.html_content:
            self.logger.error("No HTML content to parse")
            return [], "Failed to fetch content"
            
        try:
            self.soup = BeautifulSoup(self.html_content, 'html.parser')
            
            # Try multiple selectors to find main content
            content = []
            
            # Look for article content
            article = self.soup.find('article')
            if article:
                content.extend(article.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'a']))
            
            # Look for main content area
            main = self.soup.find('main')
            if main:
                content.extend(main.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'a']))
            
            # Look for div with common content class names
            content_divs = self.soup.find_all('div', class_=['content', 'post-content', 'entry-content', 'article-content'])
            for div in content_divs:
                content.extend(div.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'a']))
            
            # If no specific content area found, get all paragraphs, headers, and links
            if not content:
                content = self.soup.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'a'])
            
            # Clean and filter content
            parsed_data = []
            for elem in content:
                if elem.name == 'a':
                    href = elem.get('href')
                    if href:
                        full_url = urljoin(self.url, href)
                        parsed_data.append(f"Link: {elem.get_text(strip=True)} - {full_url}")
                else:
                    text = elem.get_text(strip=True)
                    if len(text) > 20:  # Filter out very short paragraphs
                        parsed_data.append(text)
            
            # If still no content, try Selenium
            if not parsed_data:
                self.logger.info("No content found with BeautifulSoup, trying Selenium")
                parsed_data, method = self.parse_with_selenium()
                return parsed_data, method
            
            return parsed_data, "Parsed with BeautifulSoup"
            
        except Exception as e:
            self.logger.error(f"Parsing error: {str(e)}")
            return [], f"Parsing error: {str(e)}"

    def parse_with_selenium(self):
        options = Options()
        options.add_argument("--headless")
        options.add_argument(f"user-agent={random.choice(USER_AGENTS)}")
        
        # Check if chromedriver is in the current directory
        chromedriver_path = os.path.join(os.getcwd(), 'chromedriver')
        if os.path.exists(chromedriver_path):
            driver = webdriver.Chrome(executable_path=chromedriver_path, options=options)
        else:
            # If not in the current directory, let Selenium find it in the system PATH
            driver = webdriver.Chrome(options=options)
        
        try:
            driver.get(self.url)
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            
            # Wait for dynamic content to load
            time.sleep(5)
            
            page_source = driver.page_source
            soup = BeautifulSoup(page_source, 'html.parser')
            
            content = soup.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'a'])
            parsed_data = []
            for elem in content:
                if elem.name == 'a':
                    href = elem.get('href')
                    if href:
                        full_url = urljoin(self.url, href)
                        parsed_data.append(f"Link: {elem.get_text(strip=True)} - {full_url}")
                else:
                    text = elem.get_text(strip=True)
                    if len(text) > 20:
                        parsed_data.append(text)
            
            return parsed_data, "Parsed with Selenium"
        except Exception as e:
            self.logger.error(f"Selenium parsing error: {str(e)}")
            return [], f"Selenium parsing error: {str(e)}"
        finally:
            driver.quit()

def process_url(url):
    crawler = CrawlerAgent(url)
    html_content = crawler.fetch_content()
    
    if html_content:
        parser = ParserAgent(html_content, url)
        parsed_data, method = parser.parse()
        
        if parsed_data:
            return parsed_data, method
        else:
            return None, "No content could be parsed from the page"
    else:
        return None, "Failed to fetch content"

def streamlit_app():
    st.title("Enhanced Web Content Extractor")
    
    urls = []
    for i in range(3):
        url = st.text_input(f"Enter URL {i+1} to analyze:", key=f"url_{i}", help="Enter the full URL including https://")
        if url:
            urls.append(url)
    
    if st.button("Extract Content"):
        if urls:
            cols = st.columns(len(urls))
            for i, (url, col) in enumerate(zip(urls, cols)):
                with col:
                    with st.spinner(f"Fetching and analyzing content from URL {i+1}..."):
                        result, method = process_url(url)
                        
                        with st.expander(f"Results for URL {i+1}: {url}"):
                            if result:
                                st.success(f"Content extracted successfully using {method}!")
                                
                                # Display content
                                st.subheader("Extracted Content")
                                for j, text in enumerate(result, 1):
                                    st.write(f"{j}. {text}")
                                    st.markdown("---")
                            else:
                                st.error(f"Failed to extract content: {method}")
        else:
            st.warning("Please enter at least one URL")

if __name__ == "__main__":
    streamlit_app()
