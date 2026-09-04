"""
Batch IOL Power Calculator using Barrett Universal II Formula
This script reads patient data from Excel and calculates IOL power using the web calculator.
"""

import pandas as pd
import time
from playwright.sync_api import sync_playwright
import logging
from typing import Dict, Optional
import os
import json
import re
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('iol_calculation.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# Mapping of lens models to dropdown options
LENS_MODEL_MAPPING = {
    'Alcon SN60WF': 'Alcon SN60WF',
    'Alcon SN6AD': 'Alcon SN6AD',
    'Alcon SN6ATx': 'Alcon SN6ATx',
    'Alcon SND1Tx': 'Alcon SND1Tx',
    'Alcon SV25Tx': 'Alcon SV25Tx',
    'Alcon TFNTx': 'Alcon TFNTx',
    'Alcon DFTx': 'Alcon DFTx',
    'Alcon SA60AT': 'Alcon SA60AT',
    'Alcon MN60MA': 'Alcon MN60MA',
    'Rayner RayOne EMV': 'Rayner RayOne EMV',
    'J&J ZCB00': 'J&J ZCB00',
    'J&J ZCT': 'J&J ZCT',
    'J&J ZCT(USA)': 'J&J ZCT(USA)',
    'J&J ZCU': 'J&J ZCU',
    'J&J DIU': 'J&J DIU',
    'J&J ZKU': 'J&J ZKU',
    'J&J ZLU': 'J&J ZLU',
    'J&J AR40e': 'J&J AR40e',
    'J&J AR40M': 'J&J AR40M',
    'J&J ZXR00': 'J&J ZXR00',
    'J&J ZXT': 'J&J ZXT',
    'J&J ZHR00V': 'J&J ZHR00V',
    'J&J ZHW': 'J&J ZHW',
    'Zeiss 409M': 'Zeiss 409M',
    'Zeiss 709M': 'Zeiss 709M',
    'Hoya iSert 251': 'Hoya iSert 251',
    'Hoya iSert 351': 'Hoya iSert 351',
    'Bausch & Lomb MX60': 'Bausch & Lomb MX60',
    'Bausch & Lomb MX60T': 'Bausch & Lomb MX60T',
    'Bausch & Lomb MX60ET': 'Bausch & Lomb MX60ET',
    'Bausch & Lomb MX60ET(USA)': 'Bausch & Lomb MX60ET(USA)',
    'Bausch & Lomb BL1UT': 'Bausch & Lomb BL1UT',
    'Bausch & Lomb LI60AO': 'Bausch & Lomb LI60AO',
    'MBI T302A': 'MBI T302A',
    'Lenstec SBL-3': 'Lenstec SBL-3',
    'SIFI Mini WELL': 'SIFI Mini WELL',
    'Ophtec 565': 'Ophtec 565',
}


def fill_form_field(page, label_text: str, value: str, eye_side: str = 'R'):
    """
    Fill a form field by finding the input near a label containing the specified text.
    
    Args:
        page: Playwright page object
        label_text: Text to search for in labels (e.g., 'Axial Length', 'K1')
        value: Value to fill
        eye_side: 'R' for right eye, 'L' for left eye
    """
    try:
        result = page.evaluate(f"""
            (function() {{
                const searchText = '{label_text}';
                const eyeSide = '({eye_side})';
                const value = '{value}';
                
                // Find all table rows
                const rows = Array.from(document.querySelectorAll('tr'));
                
                for (const row of rows) {{
                    const rowText = row.textContent || '';
                    // Must match both the label text and eye side
                    if (rowText.includes(searchText) && rowText.includes(eyeSide)) {{
                        // Find all cells in this row
                        const cells = Array.from(row.querySelectorAll('td'));
                        for (const cell of cells) {{
                            const cellText = cell.textContent || '';
                            // Find the cell that contains the eye side indicator AND has an input
                            if (cellText.includes(eyeSide)) {{
                                const input = cell.querySelector('input[type="text"]');
                                if (input) {{
                                    // Clear any existing value first
                                    input.focus();
                                    input.select();
                                    input.value = '';
                                    input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                    
                                    // Fill the value
                                    input.value = value;
                                    input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                    input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                    input.dispatchEvent(new Event('blur', {{ bubbles: true }}));
                                    
                                    // Verify the value was set correctly
                                    if (input.value === value) {{
                                        return true;
                                    }} else {{
                                        // Retry if value didn't stick
                                        input.focus();
                                        input.value = '';
                                        input.value = value;
                                        input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                        input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                        input.dispatchEvent(new Event('blur', {{ bubbles: true }}));
                                        return input.value === value;
                                    }}
                                }}
                            }}
                        }}
                    }}
                }}
                return false;
            }})();
        """)
        if not result:
            logging.warning(f"Could not fill {label_text} for {eye_side}")
        else:
            # Verify the field was actually filled by checking its value
            time.sleep(0.1)  # Small delay to ensure value is set
            actual_value = page.evaluate(f"""
                (function() {{
                    const searchText = '{label_text}';
                    const eyeSide = '({eye_side})';
                    const rows = Array.from(document.querySelectorAll('tr'));
                    for (const row of rows) {{
                        const rowText = row.textContent || '';
                        if (rowText.includes(searchText) && rowText.includes(eyeSide)) {{
                            const cells = Array.from(row.querySelectorAll('td'));
                            for (const cell of cells) {{
                                const cellText = cell.textContent || '';
                                if (cellText.includes(eyeSide)) {{
                                    const input = cell.querySelector('input[type="text"]');
                                    if (input) {{
                                        return input.value;
                                    }}
                                }}
                            }}
                        }}
                    }}
                    return '';
                }})();
            """)
            if actual_value != value:
                logging.warning(f"{label_text} value mismatch: expected '{value}', got '{actual_value}'")
                # Try to re-fill
                page.evaluate(f"""
                    (function() {{
                        const searchText = '{label_text}';
                        const eyeSide = '({eye_side})';
                        const value = '{value}';
                        const rows = Array.from(document.querySelectorAll('tr'));
                        for (const row of rows) {{
                            const rowText = row.textContent || '';
                            if (rowText.includes(searchText) && rowText.includes(eyeSide)) {{
                                const cells = Array.from(row.querySelectorAll('td'));
                                for (const cell of cells) {{
                                    const cellText = cell.textContent || '';
                                    if (cellText.includes(eyeSide)) {{
                                        const input = cell.querySelector('input[type="text"]');
                                        if (input) {{
                                            input.focus();
                                            input.value = value;
                                            input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                            input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                            input.dispatchEvent(new Event('blur', {{ bubbles: true }}));
                                            return input.value === value;
                                        }}
                                    }}
                                }}
                            }}
                        }}
                        return false;
                    }})();
                """)
                time.sleep(0.1)
    except Exception as e:
        logging.warning(f"Error filling {label_text} for {eye_side}: {e}")


def calculate_iol_power(
    page,
    patient_data: Dict,
    target_refraction: float = 0.0
) -> Optional[Dict]:
    """
    Calculate IOL power for a single patient using the web calculator.
    
    Args:
        page: Playwright page object
        patient_data: Dictionary containing patient data
        target_refraction: Target refraction in diopters (default: 0.0)
    
    Returns:
        Dictionary containing calculation results or None if failed
    """
    try:
        # Navigate to the calculator page
        page.goto('https://calc.apacrs.org/barrett_universal2105/', wait_until='networkidle')
        
        # Wait for page to fully load - wait for specific elements to appear
        try:
            # Wait for form inputs to be available
            page.wait_for_selector('input[type="text"]', timeout=20000)
            logging.info("Form inputs loaded")
            
            # Wait for Calculate button to be available and visible
            page.wait_for_function("""
                () => {
                    const buttons = Array.from(document.querySelectorAll('button, input[type="button"], input[type="submit"]'));
                    return buttons.some(btn => {
                        const text = (btn.textContent || btn.innerText || btn.value || '').trim();
                        return text.includes('Calculate') && !btn.disabled && btn.offsetParent !== null;
                    });
                }
            """, timeout=20000)
            logging.info("Calculate button is available")
        except Exception as e:
            logging.warning(f"Page elements not fully loaded: {e}, continuing anyway")
        
        # Determine which eye (OD or OS)
        eye_side_raw = str(patient_data.get('眼别', 'OD')).upper()
        eye_side = 'R' if (eye_side_raw == 'OD' or eye_side_raw == 'R') else 'L'
        
        # Fill patient information using JavaScript
        # Patient Name is REQUIRED - always fill with "test"
        doctor_name = patient_data.get('Doctor_Name', 'Dr. Smith')
        patient_name = "test"  # Always use "test" for Patient Name (REQUIRED field)
        patient_id = str(patient_data.get('ID', ''))
        
        # Fill doctor name, patient name, patient ID - use more precise method
        # Patient Name is REQUIRED - fill it first and ensure it's filled correctly
        fill_result = page.evaluate(f"""
            (function() {{
                const doctorName = '{doctor_name}';
                const patientName = '{patient_name}';
                const patientId = '{patient_id}';
                
                let doctorFilled = false;
                let patientNameFilled = false;
                let patientIdFilled = false;
                
                // Find inputs by their labels in table rows
                const rows = Array.from(document.querySelectorAll('tr'));
                for (const row of rows) {{
                    const rowText = row.textContent || '';
                    const cells = Array.from(row.querySelectorAll('td'));
                    
                    // Find Patient Name field - look for cell containing "Patient Name" text
                    if (rowText.includes('Patient Name')) {{
                        for (let i = 0; i < cells.length; i++) {{
                            const cell = cells[i];
                            const cellText = cell.textContent || '';
                            
                            // Find the cell that contains "Patient Name" label
                            if (cellText.includes('Patient Name')) {{
                                // The input should be in the next cell
                                if (i + 1 < cells.length) {{
                                    const nextCell = cells[i + 1];
                                    const input = nextCell.querySelector('input[type="text"]');
                                    if (input) {{
                                        input.focus();
                                        input.select();
                                        input.value = '';
                                        input.value = patientName;
                                        input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                        input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                        input.dispatchEvent(new Event('blur', {{ bubbles: true }}));
                                        
                                        // Verify it was filled
                                        if (input.value === patientName) {{
                                            patientNameFilled = true;
                                            break;
                                        }}
                                    }}
                                }}
                            }}
                        }}
                    }}
                    
                    // Find Doctor Name field
                    if (rowText.includes('Doctor Name')) {{
                        const inputs = Array.from(row.querySelectorAll('input[type="text"]'));
                        if (inputs.length > 0) {{
                            inputs[0].focus();
                            inputs[0].value = doctorName;
                            inputs[0].dispatchEvent(new Event('input', {{ bubbles: true }}));
                            inputs[0].dispatchEvent(new Event('change', {{ bubbles: true }}));
                            inputs[0].dispatchEvent(new Event('blur', {{ bubbles: true }}));
                            doctorFilled = true;
                        }}
                    }}
                    
                    // Find Patient ID field
                    if (rowText.includes('Patient ID')) {{
                        const inputs = Array.from(row.querySelectorAll('input[type="text"]'));
                        if (inputs.length > 0) {{
                            inputs[0].focus();
                            inputs[0].value = patientId;
                            inputs[0].dispatchEvent(new Event('input', {{ bubbles: true }}));
                            inputs[0].dispatchEvent(new Event('change', {{ bubbles: true }}));
                            inputs[0].dispatchEvent(new Event('blur', {{ bubbles: true }}));
                            patientIdFilled = true;
                        }}
                    }}
                }}
                
                // If Patient Name still not filled, try alternative method
                if (!patientNameFilled) {{
                    const allInputs = Array.from(document.querySelectorAll('input[type="text"]'));
                    const rows = Array.from(document.querySelectorAll('tr'));
                    for (const row of rows) {{
                        if (row.textContent.includes('Patient Name')) {{
                            const inputs = Array.from(row.querySelectorAll('input[type="text"]'));
                            // Usually Patient Name is the second input in that row (after Doctor Name)
                            if (inputs.length >= 2) {{
                                const patientNameInput = inputs[1];
                                patientNameInput.focus();
                                patientNameInput.select();
                                patientNameInput.value = '';
                                patientNameInput.value = patientName;
                                patientNameInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                patientNameInput.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                patientNameInput.dispatchEvent(new Event('blur', {{ bubbles: true }}));
                                
                                if (patientNameInput.value === patientName) {{
                                    patientNameFilled = true;
                                    break;
                                }}
                            }}
                        }}
                    }}
                }}
                
                return {{
                    doctorFilled: doctorFilled,
                    patientNameFilled: patientNameFilled,
                    patientIdFilled: patientIdFilled,
                    patientNameValue: patientNameFilled ? patientName : ''
                }};
            }})();
        """)
        
        if not fill_result.get('patientNameFilled'):
            logging.error("Failed to fill Patient Name (REQUIRED field)!")
            # Debug: check what's in the Patient Name field
            debug_info = page.evaluate("""
                (function() {
                    const rows = Array.from(document.querySelectorAll('tr'));
                    for (const row of rows) {
                        if (row.textContent.includes('Patient Name')) {
                            const inputs = Array.from(row.querySelectorAll('input[type="text"]'));
                            return {
                                rowText: row.textContent,
                                inputCount: inputs.length,
                                inputValues: inputs.map(inp => inp.value),
                                inputIds: inputs.map(inp => inp.id)
                            };
                        }
                    }
                    return null;
                })();
            """)
            logging.error(f"Patient Name field debug info: {debug_info}")
            return None
        
        # Verify Patient Name was actually filled
        actual_value = fill_result.get('patientNameValue', '')
        if actual_value != patient_name:
            logging.warning(f"Patient Name value mismatch: expected '{patient_name}', got '{actual_value}'")
        
        logging.info(f"Patient Name filled successfully: {patient_name}")
        if fill_result.get('doctorFilled'):
            logging.info(f"Doctor Name filled: {doctor_name}")
        if fill_result.get('patientIdFilled'):
            logging.info(f"Patient ID filled: {patient_id}")
        
        # Fill A Constant - use A_Constant from data directly
        # We don't select lens model, just use the A Constant value
        a_constant = patient_data.get('A_Constant', None)
        if a_constant is None:
            a_constant = 118.99  # Default value
        else:
            # Ensure a_constant is a number
            try:
                a_constant = float(a_constant)
            except (ValueError, TypeError):
                a_constant = 118.99
                logging.warning(f"Invalid A_Constant value, using default: {a_constant}")
        
        # Find and fill A Constant input - use direct method similar to built-in browser
        # Look for cell containing "(112~125)" text, then find input in that cell
        a_constant_filled = page.evaluate(f"""
            (function() {{
                const aConstantValue = '{a_constant}';
                
                // Method 1: Find cell containing "(112~125)" text, then find input in that cell
                const cells = Array.from(document.querySelectorAll('td'));
                for (const cell of cells) {{
                    const cellText = cell.textContent || '';
                    if (cellText.includes('(112~125)')) {{
                        const input = cell.querySelector('input[type="text"]');
                        if (input) {{
                            input.focus();
                            input.value = '';
                            input.value = aConstantValue;
                            input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                            input.dispatchEvent(new Event('blur', {{ bubbles: true }}));
                            return true;
                        }}
                    }}
                }}
                
                // Method 2: Find row containing "or A Constant" and "(112~125)", then find second input
                const rows = Array.from(document.querySelectorAll('tr'));
                for (const row of rows) {{
                    const rowText = row.textContent || '';
                    if (rowText.includes('or A Constant') && rowText.includes('(112~125)')) {{
                        const inputs = Array.from(row.querySelectorAll('input[type="text"]'));
                        // A Constant is typically the second input (first is Lens Factor)
                        if (inputs.length >= 2) {{
                            const aConstantInput = inputs[1];
                            aConstantInput.focus();
                            aConstantInput.value = '';
                            aConstantInput.value = aConstantValue;
                            aConstantInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            aConstantInput.dispatchEvent(new Event('change', {{ bubbles: true }}));
                            aConstantInput.dispatchEvent(new Event('blur', {{ bubbles: true }}));
                            return true;
                        }}
                    }}
                }}
                
                return false;
            }})();
        """)
        if a_constant_filled:
            logging.info(f"A Constant filled successfully: {a_constant}")
        else:
            logging.warning(f"Failed to fill A Constant: {a_constant}")
        time.sleep(0.5)
        
        # Note: We skip selecting lens model from dropdown
        # The A Constant value is sufficient for calculation
        
        # Fill measurement fields
        measurements = {
            'Axial Length': patient_data.get('AL'),
            'Measured K1': patient_data.get('K1'),
            'Measured K2': patient_data.get('K2'),
            'Optical ACD': patient_data.get('ACD'),
            'Refraction': target_refraction
        }
        
        for label, value in measurements.items():
            if value is not None:
                fill_form_field(page, label, str(value), eye_side)
        
        # Wait a moment for all fields to be filled
        time.sleep(0.5)
        
        # Verify all required fields are filled before clicking Calculate
        logging.info("Verifying required fields are filled...")
        fields_verified = page.evaluate(f"""
            (function() {{
                const requiredFields = {{
                    patientName: false,
                    aConstant: false,
                    axialLength: false,
                    k1: false,
                    k2: false,
                    acd: false,
                    refraction: false
                }};
                
                // Check Patient Name (REQUIRED - must be "test")
                const rows = Array.from(document.querySelectorAll('tr'));
                for (const row of rows) {{
                    if (row.textContent.includes('Patient Name')) {{
                        const inputs = Array.from(row.querySelectorAll('input[type="text"]'));
                        if (inputs.length >= 2) {{
                            const patientNameInput = inputs[1];
                            if (patientNameInput.value && patientNameInput.value.trim() !== '') {{
                                requiredFields.patientName = true;
                            }}
                        }}
                    }}
                    
                    // Check A Constant - find cell containing "(112~125)" and check its input
                    if (row.textContent.includes('or A Constant') || row.textContent.includes('(112~125)')) {{
                        const cells = Array.from(row.querySelectorAll('td'));
                        for (const cell of cells) {{
                            const cellText = cell.textContent || '';
                            if (cellText.includes('(112~125)')) {{
                                const input = cell.querySelector('input[type="text"]');
                                if (input && input.value && input.value.trim() !== '') {{
                                    requiredFields.aConstant = true;
                                    break;
                                }}
                            }}
                        }}
                        // Also try finding by input position in row
                        if (!requiredFields.aConstant) {{
                            const inputs = Array.from(row.querySelectorAll('input[type="text"]'));
                            if (inputs.length >= 2) {{
                                const aConstantInput = inputs[1];
                                if (aConstantInput.value && aConstantInput.value.trim() !== '') {{
                                    requiredFields.aConstant = true;
                                }}
                            }}
                        }}
                    }}
                    
                    // Check measurements for the eye side
                    const eyeSide = '({eye_side})';
                    if (row.textContent.includes('Axial Length') && row.textContent.includes(eyeSide)) {{
                        const inputs = Array.from(row.querySelectorAll('input[type="text"]'));
                        for (const input of inputs) {{
                            const cell = input.closest('td');
                            if (cell && cell.textContent.includes(eyeSide)) {{
                                if (input.value && input.value.trim() !== '') {{
                                    requiredFields.axialLength = true;
                                }}
                            }}
                        }}
                    }}
                    
                    if (row.textContent.includes('Measured K1') && row.textContent.includes(eyeSide)) {{
                        const inputs = Array.from(row.querySelectorAll('input[type="text"]'));
                        for (const input of inputs) {{
                            const cell = input.closest('td');
                            if (cell && cell.textContent.includes(eyeSide)) {{
                                if (input.value && input.value.trim() !== '') {{
                                    requiredFields.k1 = true;
                                }}
                            }}
                        }}
                    }}
                    
                    if (row.textContent.includes('Measured K2') && row.textContent.includes(eyeSide)) {{
                        const inputs = Array.from(row.querySelectorAll('input[type="text"]'));
                        for (const input of inputs) {{
                            const cell = input.closest('td');
                            if (cell && cell.textContent.includes(eyeSide)) {{
                                if (input.value && input.value.trim() !== '') {{
                                    requiredFields.k2 = true;
                                }}
                            }}
                        }}
                    }}
                    
                    if (row.textContent.includes('Optical ACD') && row.textContent.includes(eyeSide)) {{
                        const inputs = Array.from(row.querySelectorAll('input[type="text"]'));
                        for (const input of inputs) {{
                            const cell = input.closest('td');
                            if (cell && cell.textContent.includes(eyeSide)) {{
                                if (input.value && input.value.trim() !== '') {{
                                    requiredFields.acd = true;
                                }}
                            }}
                        }}
                    }}
                    
                    if (row.textContent.includes('Refraction') && row.textContent.includes(eyeSide)) {{
                        const inputs = Array.from(row.querySelectorAll('input[type="text"]'));
                        for (const input of inputs) {{
                            const cell = input.closest('td');
                            if (cell && cell.textContent.includes(eyeSide)) {{
                                if (input.value && input.value.trim() !== '') {{
                                    requiredFields.refraction = true;
                                }}
                            }}
                        }}
                    }}
                }}
                
                return requiredFields;
            }})();
        """)
        
        # Check if all required fields are filled
        missing_fields = []
        if not fields_verified.get('patientName'):
            missing_fields.append('Patient Name')
        if not fields_verified.get('aConstant'):
            missing_fields.append('A Constant')
        if not fields_verified.get('axialLength'):
            missing_fields.append('Axial Length')
        if not fields_verified.get('k1'):
            missing_fields.append('K1')
        if not fields_verified.get('k2'):
            missing_fields.append('K2')
        if not fields_verified.get('acd'):
            missing_fields.append('Optical ACD')
        if not fields_verified.get('refraction'):
            missing_fields.append('Refraction')
        
        if missing_fields:
            logging.warning(f"Some fields may be missing or empty: {', '.join(missing_fields)}")
            logging.warning(f"Fields verification result: {fields_verified}")
            # Try to re-fill missing critical fields
            if not fields_verified.get('patientName'):
                logging.info("Re-filling Patient Name...")
                page.evaluate("""
                    (function() {
                        const rows = Array.from(document.querySelectorAll('tr'));
                        for (const row of rows) {
                            if (row.textContent.includes('Patient Name')) {
                                const inputs = Array.from(row.querySelectorAll('input[type="text"]'));
                                if (inputs.length >= 2) {
                                    const patientNameInput = inputs[1];
                                    patientNameInput.focus();
                                    patientNameInput.value = 'test';
                                    patientNameInput.dispatchEvent(new Event('input', { bubbles: true }));
                                    patientNameInput.dispatchEvent(new Event('change', { bubbles: true }));
                                    patientNameInput.dispatchEvent(new Event('blur', { bubbles: true }));
                                    return true;
                                }
                            }
                        }
                        return false;
                    })();
                """)
                time.sleep(0.3)
            # Don't return None - continue anyway if only A Constant verification failed
            # (it may have been filled but verification logic is wrong)
            if 'Patient Name' in missing_fields:
                logging.error("Patient Name is required, cannot continue")
                return None
            else:
                logging.warning("Continuing despite verification warnings - fields may actually be filled")
        
        logging.info("All required fields verified and filled")
        
        # Wait for all fields to be filled and page to be ready
        try:
            # Wait for Calculate button to be enabled (not disabled)
            page.wait_for_function("""
                () => {
                    const buttons = Array.from(document.querySelectorAll('button, input[type="button"], input[type="submit"]'));
                    return buttons.some(btn => {
                        const text = (btn.textContent || btn.innerText || btn.value || '').trim();
                        return text.includes('Calculate') && !btn.disabled;
                    });
                }
            """, timeout=10000)
            logging.info("Calculate button is ready")
        except:
            logging.warning("Calculate button readiness check timeout, continuing")
        
        # Click Calculate button - use multiple methods to ensure it works
        try:
            # Use JavaScript to find and click Calculate button - more reliable for this page
            logging.info("Looking for Calculate button...")
            clicked = False
            
            # Try multiple methods to find the button (with element-based waiting)
            for attempt in range(15):
                
                clicked = page.evaluate("""
                    (function() {
                        // Method 1: Try standard button elements
                        let buttons = Array.from(document.querySelectorAll('button'));
                        for (const btn of buttons) {
                            const btnText = (btn.textContent || btn.innerText || '').trim();
                            if (btnText.includes('Calculate') && !btn.disabled) {
                                btn.focus();
                                btn.click();
                                return true;
                            }
                        }
                        
                        // Method 2: Try input[type="button"] or input[type="submit"]
                        buttons = Array.from(document.querySelectorAll('input[type="button"], input[type="submit"]'));
                        for (const btn of buttons) {
                            const btnText = (btn.value || btn.getAttribute('value') || '').trim();
                            if (btnText.includes('Calculate') && !btn.disabled) {
                                btn.focus();
                                btn.click();
                                return true;
                            }
                        }
                        
                        // Method 3: Search by text content in any clickable element
                        const allElements = Array.from(document.querySelectorAll('*'));
                        for (const el of allElements) {
                            const text = (el.textContent || el.innerText || '').trim();
                            if (text === 'Calculate' || text.includes('Calculate')) {
                                // Check if it's clickable
                                const tagName = el.tagName.toLowerCase();
                                if ((tagName === 'button' || tagName === 'input' || tagName === 'a' || 
                                     el.onclick || el.getAttribute('onclick')) && !el.disabled) {
                                    el.focus();
                                    el.click();
                                    return true;
                                }
                            }
                        }
                        
                        return false;
                    })();
                """)
                
                if clicked:
                    logging.info(f"Calculate button clicked successfully (attempt {attempt + 1})")
                    break
                
                # Wait a short time before retry, but check if button appears
                if attempt < 14:
                    try:
                        page.wait_for_function("""
                            () => {
                                const buttons = Array.from(document.querySelectorAll('button, input[type="button"], input[type="submit"]'));
                                return buttons.some(btn => {
                                    const text = (btn.textContent || btn.innerText || btn.value || '').trim();
                                    return text.includes('Calculate') && !btn.disabled;
                                });
                            }
                        """, timeout=500)
                    except:
                        pass
            
            if not clicked:
                # Debug: check what elements are available
                debug_info = page.evaluate("""
                    (function() {
                        const buttons = Array.from(document.querySelectorAll('button, input[type="button"], input[type="submit"]'));
                        const allElements = Array.from(document.querySelectorAll('*'));
                        const calculateElements = allElements.filter(el => {
                            const text = (el.textContent || el.innerText || '').trim();
                            return text.includes('Calculate');
                        });
                        return {
                            buttons: buttons.map(btn => ({
                                tag: btn.tagName,
                                text: btn.textContent || btn.innerText || btn.value || '',
                                disabled: btn.disabled,
                                id: btn.id,
                                className: btn.className
                            })),
                            calculateElements: calculateElements.map(el => ({
                                tag: el.tagName,
                                text: el.textContent || el.innerText || '',
                                id: el.id,
                                className: el.className
                            }))
                        };
                    })();
                """)
                logging.error(f"Could not find or click Calculate button. Debug info: {debug_info}")
                return None
            
            # Event-driven: wait for calculation to complete (any one indicator is enough)
            logging.info("Waiting for calculation to complete (event-driven)...")
            try:
                page.wait_for_function("""
                    () => {
                        // 1) View Formula text visible
                        const all = Array.from(document.querySelectorAll('*'));
                        for (const el of all) {
                            const t = (el.textContent || el.innerText || '').trim().toLowerCase();
                            if (t.includes('view formula') && (el.offsetParent !== null || el.checked)) return true;
                        }
                        for (const h of document.querySelectorAll('h2, h3, h4')) {
                            if ((h.textContent || '').toLowerCase().includes('view formula')) return true;
                        }
                        // 2) View Formula checkbox checked
                        for (const cb of document.querySelectorAll('checkbox, input[type="checkbox"]')) {
                            const t = (cb.textContent || cb.innerText || cb.getAttribute('aria-label') || '').toLowerCase();
                            if (t.includes('view formula') && cb.checked) return true;
                        }
                        // 3) K Index radios disabled (calculation finished)
                        for (const r of document.querySelectorAll('radio, input[type="radio"]')) {
                            const t = (r.textContent || r.innerText || '').toLowerCase();
                            if (t.includes('k index') && r.disabled) return true;
                        }
                        // 4) Recommended IOL or results table already visible
                        const body = document.body.innerText || '';
                        if (body.includes('Recommended IOL') && body.includes('Target Refraction')) return true;
                        const tables = document.querySelectorAll('table');
                        for (const tbl of tables) {
                            const tt = tbl.textContent || '';
                            if (tt.includes('IOL Power') && tt.includes('Refraction')) return true;
                        }
                        return false;
                    }
                """, timeout=15000)
                logging.info("Calculation completed (condition met)")
            except Exception as e:
                logging.warning(f"Calculation wait timeout: {e}")
            
        except Exception as e:
            logging.error(f"Error clicking Calculate button: {e}")
            import traceback
            logging.error(traceback.format_exc())
            return None
        
        # Click on Universal Formula tab to see results
        # Event-driven: wait for Universal Formula tab to be visible then click
        logging.info("Clicking Universal Formula tab to view results...")
        tab_clicked = False
        try:
            # Wait until tab is visible (returns as soon as it appears)
            universal_formula_tab = page.locator('a:has-text("Universal Formula")').first
            universal_formula_tab.wait_for(state='visible', timeout=10000)
            universal_formula_tab.scroll_into_view_if_needed()
            universal_formula_tab.click()
            tab_clicked = True
            logging.info("Universal Formula tab clicked (event-driven)")
        except Exception as e1:
            logging.debug(f"Locator click failed: {e1}")
        
        if not tab_clicked:
            try:
                tab_clicked = page.evaluate("""
                    (function() {
                        const menuitems = Array.from(document.querySelectorAll('menuitem'));
                        for (const item of menuitems) {
                            const text = (item.textContent || item.innerText || '').trim();
                            if (text.includes('Universal Formula')) {
                                const link = item.querySelector('a');
                                if (link) { link.focus(); link.click(); return true; }
                            }
                        }
                        const links = Array.from(document.querySelectorAll('a'));
                        for (const link of links) {
                            const text = (link.textContent || link.innerText || '').trim();
                            if (text === 'Universal Formula' || text.includes('Universal Formula')) {
                                link.focus(); link.click(); return true;
                            }
                        }
                        return false;
                    })();
                """)
                if tab_clicked:
                    logging.info("Universal Formula tab clicked using JavaScript")
            except Exception as e:
                logging.warning(f"Universal Formula tab click failed: {e}")
        
        if tab_clicked:
            # Event-driven: wait for results to appear (returns as soon as visible)
            try:
                page.wait_for_function("""
                    () => {
                        const textboxes = Array.from(document.querySelectorAll('textbox'));
                        for (const tb of textboxes) {
                            if ((tb.textContent || tb.innerText || '').includes('Recommended IOL')) return true;
                        }
                        for (const tbl of document.querySelectorAll('table')) {
                            const tt = tbl.textContent || '';
                            if (tt.includes('IOL Power') && tt.includes('Refraction')) return true;
                        }
                        const body = (document.body && document.body.innerText) || '';
                        if (body.includes('Recommended IOL') && body.includes('Target Refraction')) return true;
                        return false;
                    }
                """, timeout=10000)
                logging.info("Results visible (event-driven)")
            except Exception as e:
                logging.warning(f"Results wait timeout: {e}")
        else:
            logging.error("Could not click Universal Formula tab!")
            tabs_info = page.evaluate("""
                (function() {
                    const links = Array.from(document.querySelectorAll('a'));
                    return links.map(link => ({ text: (link.textContent || link.innerText || '').trim(), id: link.id }));
                })();
            """)
            logging.error(f"Available links: {tabs_info}")
        
        # Extract results (no fixed wait; rely on above event-driven waits)
        results = {}
        
        try:
            # Method 1: Use JavaScript to search textbox elements (most reliable based on page structure)
            iol_value = page.evaluate("""
                (function() {
                    // Search textbox elements for "Recommended IOL" text
                    const textboxes = Array.from(document.querySelectorAll('textbox'));
                    for (const textbox of textboxes) {
                        const text = textbox.textContent || textbox.innerText || '';
                        if (text.includes('Recommended IOL') && text.includes('Target Refraction')) {
                            // Extract number - look for pattern like "Recommended IOL: 23.3"
                            const match = text.match(/Recommended IOL[\\s:]*([\\d.]+)/);
                            if (match && match[1]) {
                                const value = parseFloat(match[1]);
                                if (!isNaN(value) && value > 0 && value < 50) {
                                    return value;
                                }
                            }
                        }
                    }
                    return null;
                })();
            """)
            if iol_value is not None:
                results['Recommended_IOL'] = float(iol_value)
                logging.info(f"Extracted Recommended IOL (Textbox JavaScript): {results['Recommended_IOL']}")
        except Exception as e:
            logging.warning(f"Textbox JavaScript method failed: {e}")
        
        # Method 2: Try Playwright textbox locator
        if 'Recommended_IOL' not in results:
            try:
                result_textboxes = page.locator('textbox').filter(has_text='Recommended IOL')
                if result_textboxes.count() > 0:
                    result_text = result_textboxes.first.inner_text()
                    # Extract IOL power from text like "Recommended IOL: 23.3 (Biconvex) for Target Refraction:-3.0"
                    iol_match = re.search(r'Recommended IOL[\\s:]*([\\d.]+)', result_text)
                    if iol_match:
                        results['Recommended_IOL'] = float(iol_match.group(1))
                        logging.info(f"Extracted Recommended IOL (Playwright Textbox): {results['Recommended_IOL']}")
            except Exception as e:
                logging.warning(f"Playwright textbox method failed: {e}")
        
        # Method 3: Search all elements as fallback
        if 'Recommended_IOL' not in results:
            try:
                iol_value = page.evaluate("""
                    (function() {
                        const allElements = Array.from(document.querySelectorAll('*'));
                        for (const el of allElements) {
                            const text = el.textContent || el.innerText || '';
                            if (text.includes('Recommended IOL') && text.includes('Target Refraction')) {
                                const match = text.match(/Recommended IOL[\\s:]*([\\d.]+)/);
                                if (match && match[1]) {
                                    const value = parseFloat(match[1]);
                                    if (!isNaN(value) && value > 0 && value < 50) {
                                        return value;
                                    }
                                }
                            }
                        }
                        return null;
                    })();
                """)
                if iol_value is not None:
                    results['Recommended_IOL'] = float(iol_value)
                    logging.info(f"Extracted Recommended IOL (All Elements): {results['Recommended_IOL']}")
            except Exception as e:
                logging.warning(f"All elements method failed: {e}")
        
        # Get IOL power table
        iol_powers = []
        try:
            # Method 1: Use JavaScript to extract table (more reliable)
            table_data = page.evaluate("""
                (function() {
                    const tables = Array.from(document.querySelectorAll('table'));
                    for (const table of tables) {
                        const tableText = table.textContent || '';
                        if (tableText.includes('IOL Power') && tableText.includes('Refraction') && tableText.includes('Biconvex')) {
                            const rows = Array.from(table.querySelectorAll('tr'));
                            const data = [];
                            for (let i = 1; i < rows.length; i++) {
                                const cells = Array.from(rows[i].querySelectorAll('td'));
                                if (cells.length >= 3) {
                                    try {
                                        const iolPowerText = cells[0].textContent.trim();
                                        const refractionText = cells[2].textContent.trim();
                                        const iolPower = parseFloat(iolPowerText);
                                        const refraction = parseFloat(refractionText);
                                        if (!isNaN(iolPower) && !isNaN(refraction) && iolPower > 0) {
                                            data.push({
                                                IOL_Power: iolPower,
                                                Refraction: refraction
                                            });
                                        }
                                    } catch(e) {}
                                }
                            }
                            if (data.length > 0) {
                                return data;
                            }
                        }
                    }
                    return [];
                })();
            """)
            if table_data:
                iol_powers = table_data
                logging.info(f"Extracted IOL power table with {len(iol_powers)} rows (JavaScript)")
        except Exception as e:
            logging.warning(f"JavaScript method failed to extract IOL power table: {e}")
        
        # Method 2: Use Playwright locator as fallback
        if len(iol_powers) == 0:
            try:
                tables = page.locator('table').filter(has_text='IOL Power')
                if tables.count() > 0:
                    table = tables.first
                    rows = table.locator('tr').all()
                    
                    for row in rows[1:]:  # Skip header
                        cells = row.locator('td').all()
                        if len(cells) >= 3:
                            try:
                                iol_power = float(cells[0].inner_text().strip())
                                refraction = float(cells[2].inner_text().strip())
                                iol_powers.append({
                                    'IOL_Power': iol_power,
                                    'Refraction': refraction
                                })
                            except:
                                pass
                    if len(iol_powers) > 0:
                        logging.info(f"Extracted IOL power table with {len(iol_powers)} rows (Playwright)")
            except Exception as e:
                logging.warning(f"Playwright method failed to extract IOL power table: {e}")
        
        results['IOL_Power_Table'] = iol_powers
        
        # Log what we extracted
        logging.info(f"Extracted results - Recommended_IOL: {results.get('Recommended_IOL', 'None')}, IOL_Power_Table rows: {len(iol_powers)}")
        
        return results
        
    except Exception as e:
        logging.error(f"Error calculating IOL power for patient {patient_data.get('ID', 'Unknown')}: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return None


def process_batch(
    input_file: str,
    output_file: str,
    target_refraction: float = 0.0,
    start_row: int = 0,
    end_row: Optional[int] = None,
    delay_between_calculations: float = 2.0
):
    """
    Process a batch of patients from Excel file.
    
    Args:
        input_file: Path to input Excel file
        output_file: Path to output Excel file
        target_refraction: Target refraction in diopters
        start_row: Starting row index (0-based)
        end_row: Ending row index (None for all rows)
        delay_between_calculations: Delay in seconds between calculations
    """
    # Read input data
    logging.info(f"Reading data from {input_file}")
    try:
        df = pd.read_excel(input_file)
    except Exception as e:
        logging.error(f"Error reading input file: {e}")
        return
    
    # Filter rows if specified
    if end_row is not None:
        df = df.iloc[start_row:end_row]
    else:
        df = df.iloc[start_row:]
    
    logging.info(f"Processing {len(df)} patients")
    
    # Prepare results list
    results_list = []
    
    # Launch browser - try to use system Chrome if available
    with sync_playwright() as p:
        # Try to find system Chrome installation
        import shutil
        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Users\{}\AppData\Local\Google\Chrome\Application\chrome.exe".format(os.getenv('USERNAME', '')),
        ]
        
        chrome_executable = None
        for path in chrome_paths:
            if os.path.exists(path):
                chrome_executable = path
                break
        
        if chrome_executable:
            logging.info(f"Using system Chrome at: {chrome_executable}")
            browser = p.chromium.launch(
                headless=False,
                executable_path=chrome_executable
            )
        else:
            # Fallback to Playwright's Chromium
            logging.info("System Chrome not found, using Playwright Chromium")
            browser = p.chromium.launch(headless=False)
        
        context = browser.new_context()
        page = context.new_page()
        
        try:
            for idx, row in df.iterrows():
                patient_id = row.get('ID', f'Row_{idx}')
                eye_side = row.get('眼别', 'OD')
                
                logging.info(f"Processing patient {patient_id}, eye {eye_side} (Row {idx + 1}/{len(df)})")
                
                # Convert row to dictionary
                patient_data = row.to_dict()
                
                # Get target refraction from "预留" column, fallback to parameter or 0.0
                target_refraction_actual = patient_data.get('预留', None)
                if target_refraction_actual is None or pd.isna(target_refraction_actual):
                    target_refraction_actual = target_refraction  # Use parameter default
                else:
                    try:
                        target_refraction_actual = float(target_refraction_actual)
                    except (ValueError, TypeError):
                        target_refraction_actual = target_refraction
                
                logging.info(f"Using target refraction: {target_refraction_actual} D (from 预留 column)")
                
                # Calculate IOL power
                result = calculate_iol_power(page, patient_data, target_refraction_actual)
                
                # Combine patient data with results
                result_row = patient_data.copy()
                if result:
                    recommended_iol = result.get('Recommended_IOL', None)
                    result_row['Recommended_IOL'] = recommended_iol
                    result_row['Calculation_Success'] = True
                    
                    # Add IOL power table as JSON string
                    iol_table = result.get('IOL_Power_Table', [])
                    result_row['IOL_Power_Table'] = json.dumps(iol_table, ensure_ascii=False) if iol_table else None
                    
                    logging.info(f"Calculation result: Recommended_IOL = {recommended_iol}")
                else:
                    result_row['Recommended_IOL'] = None
                    result_row['Calculation_Success'] = False
                    result_row['IOL_Power_Table'] = None
                    logging.warning(f"Calculation failed for patient {patient_id}")
                
                results_list.append(result_row)
                # Save after each row so partial results are kept if script crashes
                pd.DataFrame(results_list).to_excel(output_file, index=False)
                
                # Delay between calculations
                if idx < len(df) - 1:
                    time.sleep(delay_between_calculations)
        
        finally:
            browser.close()
    
    # Save results
    results_df = pd.DataFrame(results_list)
    
    # Log column names and sample data for debugging
    logging.info(f"Output columns: {list(results_df.columns)}")
    if len(results_df) > 0:
        logging.info(f"Sample row - Recommended_IOL: {results_df.iloc[0].get('Recommended_IOL', 'N/A')}")
        logging.info(f"Sample row - Calculation_Success: {results_df.iloc[0].get('Calculation_Success', 'N/A')}")
    
    results_df.to_excel(output_file, index=False)
    logging.info(f"Results saved to {output_file}")
    
    # Print summary
    if 'Calculation_Success' in results_df.columns:
        success_count = results_df['Calculation_Success'].sum()
        logging.info(f"Summary: {success_count}/{len(results_df)} calculations successful")
        if success_count > 0:
            successful_rows = results_df[results_df['Calculation_Success'] == True]
            logging.info(f"Successful calculations - Recommended_IOL values: {successful_rows['Recommended_IOL'].tolist()}")
    else:
        logging.info(f"Summary: {len(results_df)} rows processed")


if __name__ == '__main__':
    import argparse

    _data_dir = Path(__file__).resolve().parent.parent / "data"
    _default_input = str(_data_dir / "杨宁整合四文件合并_填补后.xlsx")
    _default_output = str(_data_dir / "杨宁整合四文件合并_计算结果.xlsx")

    parser = argparse.ArgumentParser(description='Batch IOL Power Calculator - Barrett Universal II Formula')
    parser.add_argument('--input', '-i', type=str, default=_default_input,
                        help='Input Excel file path')
    parser.add_argument('--output', '-o', type=str, default=_default_output,
                        help='Output Excel file path')
    parser.add_argument('--target-refraction', '-t', type=float, default=0.0,
                        help='Target refraction in diopters (default: 0.0)')
    parser.add_argument('--start-row', type=int, default=0,
                        help='Starting row index (0-based, default: 0)')
    parser.add_argument('--end-row', type=int, default=None,
                        help='Ending row index (default: None for all rows)')
    parser.add_argument('--delay', type=float, default=2.0,
                        help='Delay between calculations in seconds (default: 2.0)')
    
    args = parser.parse_args()
    
    # Check if input file exists
    if not os.path.exists(args.input):
        logging.error(f"Input file not found: {args.input}")
        logging.info("Please make sure the input file exists or specify a different file with --input")
        exit(1)
    
    process_batch(
        input_file=args.input,
        output_file=args.output,
        target_refraction=args.target_refraction,
        start_row=args.start_row,
        end_row=args.end_row,
        delay_between_calculations=args.delay
    )
