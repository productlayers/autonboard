import base64
from typing import Any

from playwright.async_api import Page


class DOMObserver:
    """Extracts interactive elements and an annotated screenshot for the LLM to understand."""

    # JavaScript to inject IDs into interactive elements and return a clean representation
    INJECT_JS = """
    () => {
        let counter = 1;
        const elements = [];
        const interactiveSelectors = 'a, button, input, select, textarea, label, [contenteditable="true"], [role="button"], [role="radio"], [role="checkbox"], [role="menuitem"], [tabindex="0"]';
        
        const candidateElements = [];
        document.querySelectorAll(interactiveSelectors).forEach(el => candidateElements.push(el));
        
        // Find custom interactive divs, spans, lis, svgs, imgs using cursor: pointer
        document.querySelectorAll('div, span, li, img, svg').forEach(el => {
            if (candidateElements.includes(el)) return;
            const style = window.getComputedStyle(el);
            if (style.cursor === 'pointer' || style.cursor === 'hand') {
                candidateElements.push(el);
            }
        });
        
        candidateElements.forEach(el => {
            const rect = el.getBoundingClientRect();
            
            // Skip hidden elements
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden' || rect.width === 0 || rect.height === 0) {
                return;
            }
            
            // Skip visually obscured elements (e.g. background elements covered by active modals/dialogs)
            try {
                const centerX = rect.left + rect.width / 2;
                const centerY = rect.top + rect.height / 2;
                const isWithinViewport = (
                    centerX >= 0 &&
                    centerY >= 0 &&
                    centerX <= window.innerWidth &&
                    centerY <= window.innerHeight
                );
                if (isWithinViewport) {
                    const topEl = document.elementFromPoint(centerX, centerY);
                    if (topEl && !el.contains(topEl) && !topEl.contains(el)) {
                        return;
                    }
                }
            } catch (e) {
                // Safely ignore cross-origin or node exceptions and do not filter out the element
            }
            
            // Assign our custom attribute
            const bffId = counter.toString();
            el.setAttribute('bff-id', bffId);
            counter++;
            const box = document.createElement('div');
            box.className = 'bff-som-box';
            box.style.position = 'absolute';
            box.style.left = (rect.left + window.scrollX) + 'px';
            box.style.top = (rect.top + window.scrollY) + 'px';
            box.style.width = rect.width + 'px';
            box.style.height = rect.height + 'px';
            box.style.border = '1px solid rgba(99, 102, 241, 0.45)';
            box.style.backgroundColor = 'rgba(99, 102, 241, 0.04)';
            box.style.borderRadius = '3px';
            box.style.zIndex = '999999';
            box.style.pointerEvents = 'none'; // Don't block clicks!
            
            // Draw ID Label — small pill badge tucked in top-left corner
            const label = document.createElement('div');
            label.style.position = 'absolute';
            label.style.top = '-1px';
            label.style.left = '-1px';
            label.style.backgroundColor = 'rgba(67, 56, 202, 0.85)';
            label.style.color = 'white';
            label.style.fontSize = '9px';
            label.style.fontWeight = '600';
            label.style.fontFamily = 'monospace';
            label.style.padding = '1px 4px';
            label.style.borderRadius = '2px 0 2px 0';
            label.style.lineHeight = '1.4';
            label.style.letterSpacing = '0.02em';
            label.innerText = bffId;
            box.appendChild(label);
            
            document.body.appendChild(box);
            
            // Extract meaningful text — keep each source separate so the LLM can distinguish
            // between current value, placeholder hint, and accessible label
            const innerText = (el.innerText || '').trim().substring(0, 50);
            const value = (el.value || '').trim().substring(0, 50);
            const placeholder = (el.placeholder || el.getAttribute('placeholder') || '').trim().substring(0, 50);
            const ariaLabel = (el.getAttribute('aria-label') || el.getAttribute('title') || '').trim().substring(0, 50);
            
            // Primary label: prefer aria-label for icon-only elements, else innerText, else value
            let text = innerText || ariaLabel || value || placeholder || el.name || '';
            
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
                value: value,          // actual typed content
                placeholder: placeholder, // hint shown when empty
                aria_label: ariaLabel,
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

    async def observe(self, page: Page) -> tuple[str, str, list[dict[str, Any]], str]:
        """
        Injects IDs into the page and returns a markdown-like string
        of all interactive elements, a base64 screenshot, the raw element data with coordinates,
        and the page title.
        """
        elements = await page.evaluate(self.INJECT_JS)

        screenshot = await page.screenshot(type="jpeg", quality=80)
        base64_image = base64.b64encode(screenshot).decode("utf-8")

        await page.evaluate(self.CLEANUP_JS)

        # Extract page title
        page_title = await page.title()

        lines = []
        for el in elements:
            type_str = f" type='{el['type']}'" if el["type"] else ""
            disabled_str = " [DISABLED]" if el.get("disabled") else ""

            # Build a rich label that distinguishes empty inputs from filled ones
            label = el["text"]
            extra = []

            # If it's an input/textarea and the visible text IS the placeholder (field is empty)
            is_input = el["tag"] in ("input", "textarea")
            has_value = bool(el.get("value", "").strip())
            placeholder = el.get("placeholder", "").strip()
            aria_label = el.get("aria_label", "").strip()

            if is_input and not has_value:
                if placeholder:
                    extra.append(f'[empty, hint: "{placeholder}"]')
                else:
                    extra.append("[empty]")
            elif is_input and has_value:
                extra.append(f'[value: "{el["value"]}"]')

            if aria_label and aria_label != label:
                extra.append(f'[aria: "{aria_label}"]')

            extra_str = " " + " ".join(extra) if extra else ""
            lines.append(f"[{el['id']}] <{el['tag']}{type_str}>{disabled_str} {label}{extra_str}")

        return "\n".join(lines), base64_image, elements, page_title
