from typing import Dict, Any, Tuple
from playwright.async_api import Page
import base64

class DOMObserver:
    """Extracts interactive elements and an annotated screenshot for the LLM to understand."""

    # JavaScript to inject IDs into interactive elements and return a clean representation
    INJECT_JS = """
    () => {
        let counter = 1;
        const elements = [];
        const interactiveSelectors = 'a, button, input, select, textarea, label, [role="button"], [role="radio"], [role="checkbox"], [role="menuitem"], [tabindex="0"]';
        
        document.querySelectorAll(interactiveSelectors).forEach(el => {
            // Skip hidden elements
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden' || el.offsetWidth === 0 || el.offsetHeight === 0) {
                return;
            }
            
            // Assign our custom attribute
            const bffId = counter.toString();
            el.setAttribute('bff-id', bffId);
            counter++;
            
            // Draw Bounding Box for Vision Model
            const rect = el.getBoundingClientRect();
            const box = document.createElement('div');
            box.className = 'bff-som-box';
            box.style.position = 'absolute';
            box.style.left = (rect.left + window.scrollX) + 'px';
            box.style.top = (rect.top + window.scrollY) + 'px';
            box.style.width = rect.width + 'px';
            box.style.height = rect.height + 'px';
            box.style.border = '2px solid red';
            box.style.backgroundColor = 'rgba(255, 0, 0, 0.1)';
            box.style.zIndex = '999999';
            box.style.pointerEvents = 'none'; // Don't block clicks!
            
            // Draw ID Label
            const label = document.createElement('div');
            label.style.position = 'absolute';
            label.style.top = '-15px';
            label.style.left = '0';
            label.style.backgroundColor = 'yellow';
            label.style.color = 'black';
            label.style.fontSize = '12px';
            label.style.fontWeight = 'bold';
            label.style.padding = '0 2px';
            label.innerText = bffId;
            box.appendChild(label);
            
            document.body.appendChild(box);
            
            // Extract meaningful text
            let text = el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || el.name || '';
            text = text.trim().substring(0, 50); // Keep it short
            
            // Check if element is disabled
            let disabled = el.disabled || el.getAttribute('aria-disabled') === 'true';
            
            // Calculate center coordinates
            const centerX = Math.round(rect.left + window.scrollX + (rect.width / 2));
            const centerY = Math.round(rect.top + window.scrollY + (rect.height / 2));
            
            elements.push({
                id: bffId,
                tag: el.tagName.toLowerCase(),
                type: el.type || '',
                text: text,
                disabled: disabled,
                x: centerX,
                y: centerY
            });
        });
        
        return elements;
    }
    """

    CLEANUP_JS = """
    () => {
        document.querySelectorAll('.bff-som-box').forEach(el => el.remove());
    }
    """

    async def observe(self, page: Page) -> Tuple[str, str, list[Dict[str, Any]], str]:
        """
        Injects IDs into the page and returns a markdown-like string 
        of all interactive elements, a base64 screenshot, the raw element data with coordinates,
        and the page title.
        """
        elements = await page.evaluate(self.INJECT_JS)
        
        screenshot = await page.screenshot(type="jpeg", quality=80)
        base64_image = base64.b64encode(screenshot).decode('utf-8')
        
        await page.evaluate(self.CLEANUP_JS)
        
        # Extract page title
        page_title = await page.title()
        
        lines = []
        for el in elements:
            type_str = f" type='{el['type']}'" if el['type'] else ""
            disabled_str = " [DISABLED]" if el.get('disabled') else ""
            lines.append(f"[{el['id']}] <{el['tag']}{type_str}>{disabled_str} {el['text']}")
            
        return "\n".join(lines), base64_image, elements, page_title
