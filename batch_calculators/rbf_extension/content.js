(function () {
  'use strict';

  const MEASURING_DEVICE = 'ZEISS IOLMASTER 700';
  const MOCK_PATIENT = {
    id_email: 'sample@local',
    name: 'Sample',
    first_name: 'Patient',
    dob: '01.01.1960',
    gender: 'Not provided'
  };

  function byName(name) {
    return document.querySelector('input[name="' + name + '"], textarea[name="' + name + '"]');
  }
  function byLabelText(text) {
    const cells = document.querySelectorAll('td, th');
    for (let i = 0; i < cells.length; i++) {
      if (cells[i].textContent && cells[i].textContent.indexOf(text) !== -1) {
        const row = cells[i].closest('tr');
        if (row) {
          const input = row.querySelector('input[type="text"], input:not([type]), select');
          if (input && input.offsetParent !== null) return input;
          let next = cells[i].nextElementSibling;
          for (let j = 0; j < 3 && next; j++) {
            const inp = next.querySelector('input, select');
            if (inp && inp.offsetParent !== null) return inp;
            next = next.nextElementSibling;
          }
        }
      }
    }
    return null;
  }
  function byLabelOrPlaceholder(labelText, placeholderPart) {
    const byLabel = byLabelText(labelText);
    if (byLabel) return byLabel;
    if (placeholderPart) {
      const all = document.querySelectorAll('input');
      for (let i = 0; i < all.length; i++) {
        if (all[i].placeholder && all[i].placeholder.indexOf(placeholderPart) !== -1) return all[i];
      }
    }
    const all = document.querySelectorAll('label, .form-group, div');
    for (let i = 0; i < all.length; i++) {
      if (all[i].textContent && all[i].textContent.trim().indexOf(labelText) === 0) {
        const inp = all[i].querySelector('input, select') || all[i].nextElementSibling && all[i].nextElementSibling.querySelector('input, select');
        if (inp && inp.offsetParent !== null) return inp;
      }
    }
    return null;
  }

  function setVal(el, val) {
    if (!el) return;
    el.focus();
    el.value = val;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function selectOption(sel, label) {
    if (!sel || sel.tagName !== 'SELECT') return;
    const opts = sel.options;
    for (let i = 0; i < opts.length; i++) {
      if (opts[i].text.indexOf(label) !== -1) {
        sel.selectedIndex = i;
        sel.dispatchEvent(new Event('change', { bubbles: true }));
        return;
      }
    }
  }

  function fillPatient(p) {
    var mock = Object.assign({}, MOCK_PATIENT, (p && p.gender) ? { gender: p.gender } : {});
    var idEl = document.querySelector('input[name="id_email"]') || document.querySelector('input[placeholder*="E-Mail"]') || byLabelText('ID') || byLabelOrPlaceholder('ID');
    if (idEl) setVal(idEl, mock.id_email);
    var nameEl = document.querySelectorAll('input[name="name"]')[0] || byLabelText('Name') || byLabelOrPlaceholder('Name');
    if (nameEl) setVal(nameEl, mock.name);
    var firstEl = document.querySelectorAll('input[name="first_name"]')[0] || document.querySelectorAll('input[name="firstname"]')[0] || byLabelText('First name') || byLabelOrPlaceholder('First name');
    if (firstEl) setVal(firstEl, mock.first_name);
    var dobEl = document.querySelector('input[placeholder*="DD.MM"]') || document.querySelector('input[name="dob"]') || byLabelText('Date of birth') || byLabelOrPlaceholder('Date of birth', 'DD.MM');
    if (dobEl) setVal(dobEl, mock.dob);
    var genderSel = document.querySelector('select[name="gender"]') || byLabelText('Gender') || byLabelOrPlaceholder('Gender');
    if (genderSel) selectOption(genderSel, mock.gender);
    var patientSection = document.querySelector('body');
    if (patientSection && (!idEl || !nameEl || !firstEl || !dobEl)) {
      var inputs = patientSection.querySelectorAll('input[type="text"]:not([disabled]), input:not([type]):not([disabled])');
      var idx = 0;
      for (var i = 0; i < inputs.length; i++) {
        if (inputs[i].offsetParent === null) continue;
        var ph = (inputs[i].placeholder || '') + (inputs[i].name || '') + (inputs[i].id || '');
        if (ph.indexOf('Calculation') !== -1) break;
        if (idx === 0) setVal(inputs[i], mock.id_email);
        else if (idx === 1) setVal(inputs[i], mock.name);
        else if (idx === 2) setVal(inputs[i], mock.first_name);
        else if (idx === 3 && (inputs[i].placeholder || '').indexOf('DD') !== -1) { setVal(inputs[i], mock.dob); idx++; }
        if (idx < 4) idx++;
      }
    }
  }

  function clickIagree() {
    const btns = document.querySelectorAll('button');
    for (let i = 0; i < btns.length; i++) {
      if (btns[i].textContent && btns[i].textContent.indexOf('I agree') !== -1) {
        btns[i].click();
        return true;
      }
    }
    return false;
  }

  function fillOneEye(eyeSide, eyeData, iol) {
    const isOd = (eyeSide || 'od').toLowerCase() === 'od';
    const deviceCandidates = [];
    const selects = document.querySelectorAll('select');
    for (let i = 0; i < selects.length; i++) {
      if (selects[i].options && selects[i].options[0] && selects[i].options[0].text.indexOf('Please select used measuring') !== -1) {
        deviceCandidates.push(selects[i]);
      }
    }
    const deviceSelect = isOd ? deviceCandidates[0] : deviceCandidates[1];
    if (deviceSelect && !deviceSelect.disabled) selectOption(deviceSelect, MEASURING_DEVICE);

    const rows = document.querySelectorAll('tr');
    function fillInRow(labelText, value, eyeChar) {
      const eyeChar2 = eyeChar || (isOd ? '(R)' : '(L)');
      for (let r = 0; r < rows.length; r++) {
        const txt = rows[r].textContent || '';
        if (txt.indexOf(labelText) !== -1 && txt.indexOf(eyeChar2) !== -1) {
          const cells = rows[r].querySelectorAll('td');
          for (let c = 0; c < cells.length; c++) {
            if (cells[c].textContent && cells[c].textContent.indexOf(eyeChar2) !== -1) {
              const inp = cells[c].querySelector('input[type="text"], input:not([type])');
              if (inp && !inp.disabled) {
                setVal(inp, value);
                return true;
              }
            }
          }
        }
      }
      return false;
    }

    const eyeChar = isOd ? '(R)' : '(L)';
    fillInRow('Target Refr', eyeData.target_refr || '0.00', eyeChar);
    fillInRow('Axial Length', eyeData.al || '', eyeChar) || fillInRow('AL', eyeData.al || '', eyeChar);
    fillInRow('CCT', eyeData.cct || '', eyeChar);
    fillInRow('Optical ACD', eyeData.acd || '', eyeChar) || fillInRow('ACD', eyeData.acd || '', eyeChar);
    fillInRow('Lens Thickness', eyeData.lt || '', eyeChar) || fillInRow('LT', eyeData.lt || '', eyeChar);
    fillInRow('Measured K1', eyeData.k1 || '', eyeChar) || fillInRow('K1', eyeData.k1 || '', eyeChar);
    fillInRow('Measured K2', eyeData.k2 || '', eyeChar) || fillInRow('K2', eyeData.k2 || '', eyeChar);
    fillInRow('WTW', eyeData.wtw || '', eyeChar);
    fillInRow('Manufacturer', iol.manufacturer || 'Alcon', eyeChar);
    fillInRow('Model', iol.model || 'SN60WF', eyeChar);
    fillInRow('A-Constant', iol.a_constant || '118.5', eyeChar) || fillInRow('A-Constant', iol.a_constant || '118.5', eyeChar);

    const nSelects = document.querySelectorAll('select');
    for (let i = 0; i < nSelects.length; i++) {
      const o = nSelects[i].options;
      for (let j = 0; j < o.length; j++) {
        if (o[j].text === '1.3375') {
          const par = nSelects[i].closest('tr');
          if (par && par.textContent.indexOf(eyeChar) !== -1) {
            nSelects[i].selectedIndex = j;
            nSelects[i].dispatchEvent(new Event('change', { bubbles: true }));
            break;
          }
        }
      }
    }
  }

  function doFill(payload, doc) {
    doc = doc || document;
    if (!payload) return;
    var clickIagreeFn = function () {
      var btns = doc.querySelectorAll('button');
      for (var i = 0; i < btns.length; i++) {
        if (btns[i].textContent && btns[i].textContent.indexOf('I agree') !== -1) {
          btns[i].click();
          return true;
        }
      }
      return false;
    };
    var fillPatientFn = function (p) {
      var mock = Object.assign({}, MOCK_PATIENT, p || {});
      var setValFn = function (el, val) {
        if (!el) return;
        el.focus();
        el.value = val;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
      };
      var idEl = doc.getElementById('pat_id') || doc.querySelector('input[name="pat_id"]');
      if (idEl) setValFn(idEl, mock.id_email || mock.id || '');
      var nameEl = doc.getElementById('pat_lastname') || doc.querySelector('input[name="pat_lastname"]');
      if (nameEl) setValFn(nameEl, mock.name || '');
      var firstEl = doc.getElementById('pat_firstname') || doc.querySelector('input[name="pat_firstname"]');
      if (firstEl) setValFn(firstEl, mock.first_name || mock.firstname || '');
      var dobEl = doc.getElementById('pat_birthday') || doc.querySelector('input[name="pat_birthday"]');
      if (dobEl) setValFn(dobEl, mock.dob || '');
      var genderSel = doc.getElementById('pat_gender') || doc.querySelector('select[name="pat_gender"]');
      if (genderSel) {
        var g = (mock.gender || 'Not provided').trim();
        for (var k = 0; k < genderSel.options.length; k++) {
          if (genderSel.options[k].text.indexOf(g) !== -1) { genderSel.selectedIndex = k; genderSel.dispatchEvent(new Event('change', { bubbles: true })); break; }
        }
      }
      var byLabel = function (text) {
        var cells = doc.querySelectorAll('td, th');
        for (var i = 0; i < cells.length; i++) {
          if (cells[i].textContent && cells[i].textContent.indexOf(text) !== -1) {
            var row = cells[i].closest('tr');
            if (row) {
              var input = row.querySelector('input[type="text"], input:not([type]), select');
              if (input && input.offsetParent !== null) return input;
              var next = cells[i].nextElementSibling;
              for (var j = 0; j < 3 && next; j++) {
                var inp = next.querySelector('input, select');
                if (inp && inp.offsetParent !== null) return inp;
                next = next.nextElementSibling;
              }
            }
          }
        }
        return null;
      };
      if (!idEl) {
        var inp0 = doc.querySelector('input[name="id_email"]') || doc.querySelector('input[placeholder*="E-Mail"]') || byLabel('ID');
        if (inp0) setValFn(inp0, mock.id_email || mock.id || '');
      }
      if (!nameEl) { var inp1 = doc.querySelectorAll('input[name="name"]')[0] || byLabel('Name'); if (inp1) setValFn(inp1, mock.name || ''); }
      if (!firstEl) { var inp2 = doc.querySelectorAll('input[name="first_name"]')[0] || doc.querySelectorAll('input[name="firstname"]')[0] || byLabel('First name'); if (inp2) setValFn(inp2, mock.first_name || mock.firstname || ''); }
      if (!dobEl) { var inp3 = doc.querySelector('input[placeholder*="DD.MM"]') || doc.querySelector('input[name="dob"]') || byLabel('Date of birth'); if (inp3) setValFn(inp3, mock.dob || ''); }
      if (!genderSel) { var sel = doc.querySelector('select[name="gender"]') || byLabel('Gender'); if (sel) { for (var k = 0; k < sel.options.length; k++) { if (sel.options[k].text.indexOf(mock.gender || 'Not provided') !== -1) { sel.selectedIndex = k; sel.dispatchEvent(new Event('change', { bubbles: true })); break; } } } }
    };
    var setValFn = function (el, val) {
      if (!el) return;
      el.focus();
      el.value = val;
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    };
    var fillOneEyeInDoc_Step1_DeviceOnly = function (documentRef, eyeSide) {
      var d = documentRef || doc;
      var isOd = (eyeSide || 'od').toLowerCase() === 'od';
      var deviceCandidates = Array.prototype.slice.call(d.querySelectorAll('select[name="measuringDevice"]'));
      if (deviceCandidates.length === 0) {
        var selects = d.querySelectorAll('select');
        for (var s = 0; s < selects.length; s++) {
          if (selects[s].options[0] && selects[s].options[0].text.indexOf('Please select used measuring') !== -1) deviceCandidates.push(selects[s]);
        }
      }
      var dev = isOd ? deviceCandidates[0] : deviceCandidates[1];
      if (dev && !dev.disabled) {
        for (var o = 0; o < dev.options.length; o++) {
          if (dev.options[o].text.indexOf(MEASURING_DEVICE) !== -1) { dev.selectedIndex = o; dev.dispatchEvent(new Event('change', { bubbles: true })); break; }
        }
      }
    };
    var fillOneEyeInDoc_Step2_MeasurementsAndIOL = function (documentRef, eyeSide, eyeData, iol) {
      var d = documentRef || doc;
      var isOd = (eyeSide || 'od').toLowerCase() === 'od';
      var colIndex = isOd ? 0 : 1;
      var prefix = isOd ? 'od_' : 'os_';
      var alEl = d.getElementById(prefix + 'al');
      if (alEl) {
        var setById = function (suffix, val) {
          if (val === undefined || val === null) return;
          var el = d.getElementById(prefix + suffix);
          if (!el) return;
          if (el.tagName === 'SELECT' && el.disabled) return;
          setValFn(el, String(val));
        };
        setById('target_refr', eyeData.target_refr || '0.00');
        setById('al', eyeData.al);
        setById('cct', eyeData.cct);
        setById('acd', eyeData.acd);
        setById('lt', eyeData.lt);
        setById('k1', eyeData.k1);
        setById('k1Axis', eyeData.k1_axis);
        setById('k2', eyeData.k2);
        setById('k2Axis', eyeData.k2_axis);
        setById('wtw', eyeData.wtw);
        setById('manufacturer', iol.manufacturer || 'Alcon');
        setById('model', iol.model || 'SN60WF');
        setById('aconstant', iol.a_constant || '118.5');
        var nSel = d.getElementById(prefix + 'n');
        if (nSel && !nSel.disabled) {
          for (var ni = 0; ni < nSel.options.length; ni++) {
            if (nSel.options[ni].text === '1.3375') { nSel.selectedIndex = ni; nSel.dispatchEvent(new Event('change', { bubbles: true })); break; }
          }
        }
        return;
      }
      var rows = d.querySelectorAll('tr');
      var fillRowByCol = function (labelText, value) {
        for (var r = 0; r < rows.length; r++) {
          var txt = rows[r].textContent || '';
          if (txt.indexOf(labelText) === -1) continue;
          var collectInputs = function (rowEl) {
            var inputs = [];
            if (!rowEl) return inputs;
            rowEl.querySelectorAll('input[type="text"]:not([disabled]), input:not([type]):not([disabled])').forEach(function (inp) {
              if (inp.offsetParent !== null) inputs.push(inp);
            });
            if (inputs.length === 0) {
              rowEl.querySelectorAll('td').forEach(function (cell) {
                var inp = cell.querySelector('input[type="text"], input:not([type])');
                if (inp && !inp.disabled && inp.offsetParent !== null) inputs.push(inp);
              });
            }
            return inputs;
          };
          var inputs = collectInputs(rows[r]);
          if (inputs.length === 0 && rows[r].nextElementSibling) inputs = collectInputs(rows[r].nextElementSibling);
          if (inputs.length > colIndex) {
            var idx = colIndex;
            if (inputs.length >= 4 && (labelText.indexOf('K1') !== -1 || labelText.indexOf('K2') !== -1)) idx = colIndex * 2;
            setValFn(inputs[idx], value);
            return true;
          }
        }
        return false;
      };
      var fillRowByEyeChar = function (labelText, value, eyeChar) {
        for (var r = 0; r < rows.length; r++) {
          var txt = rows[r].textContent || '';
          if (txt.indexOf(labelText) === -1 || txt.indexOf(eyeChar) === -1) continue;
          var cells = rows[r].querySelectorAll('td');
          for (var c = 0; c < cells.length; c++) {
            if (cells[c].textContent.indexOf(eyeChar) === -1) continue;
            var inp = cells[c].querySelector('input[type="text"], input:not([type])');
            if (inp && !inp.disabled && inp.offsetParent !== null) {
              setValFn(inp, value);
              return true;
            }
          }
        }
        return false;
      };
      var eyeChar = isOd ? '(R)' : '(L)';
      fillRowByCol('Target Refr', eyeData.target_refr || '0.00') || fillRowByEyeChar('Target Refr', eyeData.target_refr || '0.00', eyeChar);
      fillRowByCol('Axial Length', eyeData.al || '') || fillRowByCol('AL', eyeData.al || '') || fillRowByEyeChar('AL', eyeData.al || '', eyeChar);
      fillRowByCol('CCT', eyeData.cct || '') || fillRowByEyeChar('CCT', eyeData.cct || '', eyeChar);
      fillRowByCol('Optical ACD', eyeData.acd || '') || fillRowByCol('ACD', eyeData.acd || '') || fillRowByEyeChar('ACD', eyeData.acd || '', eyeChar);
      fillRowByCol('Lens Thickness', eyeData.lt || '') || fillRowByCol('LT', eyeData.lt || '') || fillRowByEyeChar('LT', eyeData.lt || '', eyeChar);
      fillRowByCol('Measured K1', eyeData.k1 || '') || fillRowByCol('K1', eyeData.k1 || '') || fillRowByEyeChar('K1', eyeData.k1 || '', eyeChar);
      fillRowByCol('Measured K2', eyeData.k2 || '') || fillRowByCol('K2', eyeData.k2 || '') || fillRowByEyeChar('K2', eyeData.k2 || '', eyeChar);
      fillRowByCol('WTW', eyeData.wtw || '') || fillRowByEyeChar('WTW', eyeData.wtw || '', eyeChar);
      fillRowByCol('Manufacturer', iol.manufacturer || 'Alcon') || fillRowByEyeChar('Manufacturer', iol.manufacturer || 'Alcon', eyeChar);
      fillRowByCol('Model', iol.model || 'SN60WF') || fillRowByEyeChar('Model', iol.model || 'SN60WF', eyeChar);
      fillRowByCol('A-Constant', iol.a_constant || '118.5') || fillRowByEyeChar('A-Constant', iol.a_constant || '118.5', eyeChar);
      var sectionByHeading = null;
      var allNodes = d.querySelectorAll('h2, h3, h4, span, div, label');
      for (var hi = 0; hi < allNodes.length; hi++) {
        var ht = (allNodes[hi].textContent || '').trim().toLowerCase();
        if (ht !== 'od' && ht !== 'os') continue;
        var container = allNodes[hi].parentElement;
        if (!container) continue;
        if ((isOd && ht !== 'od') || (!isOd && ht !== 'os')) continue;
        for (var up = 0; up < 15 && container; up++) {
          if (container.querySelectorAll('input').length >= 6) {
            sectionByHeading = container;
            break;
          }
          container = container.parentElement;
        }
        if (sectionByHeading) break;
      }
      if (!sectionByHeading) {
        var need = isOd ? 'od' : 'os';
        var best = null;
        var divs = d.querySelectorAll('div');
        for (var di = 0; di < divs.length; di++) {
          var dt = (divs[di].textContent || '').toLowerCase();
          var n = divs[di].querySelectorAll('input').length;
          if (n < 6 || dt.indexOf('target refr') === -1 || dt.indexOf(need) === -1) continue;
          if (!best || n < best.querySelectorAll('input').length) best = divs[di];
        }
        if (best) sectionByHeading = best;
      }
      var findInputByLabel = function (section, labelParts, value) {
        if (!value && value !== 0) return false;
        var byFor = section.querySelectorAll('label');
        for (var li = 0; li < byFor.length; li++) {
          var lt = (byFor[li].textContent || '').trim();
          for (var lp = 0; lp < labelParts.length; lp++) {
            if (lt.indexOf(labelParts[lp]) === -1) continue;
            var id = byFor[li].getAttribute('for');
            if (id) {
              var inp = section.querySelector('#' + id) || d.getElementById(id);
              if (inp && !inp.disabled && inp.offsetParent !== null) { setValFn(inp, String(value)); return true; }
            }
            var inp = byFor[li].querySelector('input');
            if (inp && !inp.disabled && inp.offsetParent !== null) { setValFn(inp, String(value)); return true; }
            break;
          }
        }
        var all = section.querySelectorAll('*');
        for (var ai = 0; ai < all.length; ai++) {
          var txt = (all[ai].textContent || '').trim();
          if (txt.length > 80) continue;
          var match = false;
          for (var lp = 0; lp < labelParts.length; lp++) {
            if (txt.indexOf(labelParts[lp]) !== -1) { match = true; break; }
          }
          if (!match) continue;
          var inp = all[ai].querySelector('input[type="text"], input:not([type])');
          if (!inp && all[ai].nextElementSibling) inp = all[ai].nextElementSibling.querySelector('input');
          if (!inp) {
            var next = all[ai].nextElementSibling;
            for (var n = 0; n < 5 && next; n++) {
              inp = next.querySelector ? next.querySelector('input') : null;
              if (inp) break;
              next = next.nextElementSibling;
            }
          }
          if (inp && !inp.disabled && inp.offsetParent !== null) {
            setValFn(inp, String(value));
            return true;
          }
        }
        return false;
      };
      if (sectionByHeading) {
        findInputByLabel(sectionByHeading, ['Target Refr', 'Target Refr.'], eyeData.target_refr || '0.00');
        findInputByLabel(sectionByHeading, ['Axial Length', 'AL'], eyeData.al || '');
        findInputByLabel(sectionByHeading, ['CCT'], eyeData.cct || '');
        findInputByLabel(sectionByHeading, ['Optical ACD', 'ACD'], eyeData.acd || '');
        findInputByLabel(sectionByHeading, ['Lens Thickness', 'LT'], eyeData.lt || '');
        findInputByLabel(sectionByHeading, ['Measured K1', 'K1'], eyeData.k1 || '');
        findInputByLabel(sectionByHeading, ['Measured K2', 'K2'], eyeData.k2 || '');
        findInputByLabel(sectionByHeading, ['WTW'], eyeData.wtw || '');
        findInputByLabel(sectionByHeading, ['Manufacturer'], iol.manufacturer || 'Alcon');
        findInputByLabel(sectionByHeading, ['Model'], iol.model || 'SN60WF');
        findInputByLabel(sectionByHeading, ['A-Constant', 'A-Constant'], iol.a_constant || '118.5');
      }
      var nSelects = [];
      d.querySelectorAll('select').forEach(function (sel) {
        for (var ni = 0; ni < sel.options.length; ni++) {
          if (sel.options[ni].text === '1.3375') { nSelects.push(sel); break; }
        }
      });
      if (nSelects[colIndex] && !nSelects[colIndex].disabled) {
        for (var ni = 0; ni < nSelects[colIndex].options.length; ni++) {
          if (nSelects[colIndex].options[ni].text === '1.3375') {
            nSelects[colIndex].selectedIndex = ni;
            nSelects[colIndex].dispatchEvent(new Event('change', { bubbles: true }));
            break;
          }
        }
      }
    };
    var runFillEyeAfterPatient = function () {
      fillOneEyeInDoc_Step1_DeviceOnly(doc, payload.eye_side);
      var isOd = (payload.eye_side || 'od').toLowerCase() === 'od';
      var alId = isOd ? 'od_al' : 'os_al';
      var step2 = function () {
        fillOneEyeInDoc_Step2_MeasurementsAndIOL(doc, payload.eye_side, payload.eye_data || {}, payload.iol || {});
      };
      var start = Date.now();
      var maxWait = 2500;
      var interval = setInterval(function () {
        var el = doc.getElementById(alId);
        if (el && !el.disabled) {
          clearInterval(interval);
          step2();
          return;
        }
        if (Date.now() - start > maxWait) {
          clearInterval(interval);
          step2();
        }
      }, 150);
    };
    if (clickIagreeFn()) {
      setTimeout(function () {
        fillPatientFn(payload.patient || {});
        setTimeout(runFillEyeAfterPatient, 700);
      }, 300);
    } else {
      fillPatientFn(payload.patient || {});
      setTimeout(runFillEyeAfterPatient, 600);
    }
  }

  function doFillMissing(payload, doc) {
    doc = doc || document;
    if (!payload) return;
    var setValFn = function (el, val) {
      if (!el) return;
      el.focus();
      el.value = val;
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    };
    var isEmpty = function (el) {
      if (!el) return true;
      var v = (el.value || '').trim();
      return v === '';
    };
    var p = payload.patient || {};
    var eyeData = payload.eye_data || {};
    var iol = payload.iol || {};
    var isOd = (payload.eye_side || 'od').toLowerCase() === 'od';
    var prefix = isOd ? 'od_' : 'os_';

    var idPat = ['pat_id', p.id_email || p.id], lastPat = ['pat_lastname', p.name], firstPat = ['pat_firstname', p.first_name || p.firstname], dobPat = ['pat_birthday', p.dob];
    [idPat, lastPat, firstPat, dobPat].forEach(function (pair) {
      var el = doc.getElementById(pair[0]);
      if (el && isEmpty(el) && pair[1] != null && pair[1] !== '') setValFn(el, String(pair[1]));
    });
    var genderSel = doc.getElementById('pat_gender');
    if (genderSel && p.gender) {
      var want = (p.gender || 'Not provided').trim();
      var cur = genderSel.options[genderSel.selectedIndex] ? genderSel.options[genderSel.selectedIndex].text : '';
      if (!cur || cur.indexOf('Please') !== -1) {
        for (var k = 0; k < genderSel.options.length; k++) {
          if (genderSel.options[k].text.indexOf(want) !== -1) { genderSel.selectedIndex = k; genderSel.dispatchEvent(new Event('change', { bubbles: true })); break; }
        }
      }
    }

    var deviceCandidates = Array.prototype.slice.call(doc.querySelectorAll('select[name="measuringDevice"]'));
    if (deviceCandidates.length === 0) {
      var selects = doc.querySelectorAll('select');
      for (var s = 0; s < selects.length; s++) {
        if (selects[s].options[0] && selects[s].options[0].text.indexOf('Please select used measuring') !== -1) deviceCandidates.push(selects[s]);
      }
    }
    var dev = isOd ? deviceCandidates[0] : deviceCandidates[1];
    var needDevice = dev && dev.options[0] && dev.options[0].text.indexOf('Please select') !== -1;
    if (needDevice && dev && !dev.disabled) {
      for (var o = 0; o < dev.options.length; o++) {
        if (dev.options[o].text.indexOf(MEASURING_DEVICE) !== -1) { dev.selectedIndex = o; dev.dispatchEvent(new Event('change', { bubbles: true })); break; }
      }
    }

    var fillEyeEmpty = function () {
      var setIfEmpty = function (suffix, val) {
        if (val === undefined || val === null) return;
        var el = doc.getElementById(prefix + suffix);
        if (!el || !isEmpty(el)) return;
        if (el.tagName === 'SELECT' && el.disabled) return;
        setValFn(el, String(val));
      };
      setIfEmpty('target_refr', eyeData.target_refr || '0.00');
      setIfEmpty('al', eyeData.al);
      setIfEmpty('cct', eyeData.cct);
      setIfEmpty('acd', eyeData.acd);
      setIfEmpty('lt', eyeData.lt);
      setIfEmpty('k1', eyeData.k1);
      setIfEmpty('k1Axis', eyeData.k1_axis);
      setIfEmpty('k2', eyeData.k2);
      setIfEmpty('k2Axis', eyeData.k2_axis);
      setIfEmpty('wtw', eyeData.wtw);
      setIfEmpty('manufacturer', iol.manufacturer || 'Alcon');
      setIfEmpty('model', iol.model || 'SN60WF');
      setIfEmpty('aconstant', iol.a_constant || '118.5');
      var nSel = doc.getElementById(prefix + 'n');
      if (nSel && !nSel.disabled) {
        var curOpt = nSel.options[nSel.selectedIndex] ? nSel.options[nSel.selectedIndex].text : '';
        if (curOpt !== '1.3375') {
          for (var ni = 0; ni < nSel.options.length; ni++) {
            if (nSel.options[ni].text === '1.3375') { nSel.selectedIndex = ni; nSel.dispatchEvent(new Event('change', { bubbles: true })); break; }
          }
        }
      }
    };

    if (needDevice) setTimeout(fillEyeEmpty, 1200);
    else fillEyeEmpty();
  }

  function doFillSameDoc(payload) {
    if (!payload) return;
    var runEyeAfter = function () {
      setTimeout(function () { fillOneEye(payload.eye_side, payload.eye_data || {}, payload.iol || {}); }, 600);
    };
    if (clickIagree()) {
      setTimeout(function () {
        fillPatient(payload.patient || {});
        setTimeout(runEyeAfter, 700);
      }, 300);
    } else {
      fillPatient(payload.patient || {});
      setTimeout(runEyeAfter, 600);
    }
  }

  function doClickCalculate(doc) {
    doc = doc || document;
    var nodes = doc.querySelectorAll('button, a, div, span, [role="button"]');
    for (var i = 0; i < nodes.length; i++) {
      var t = (nodes[i].textContent || '').trim();
      if (t.indexOf('Click to calculate') !== -1) {
        nodes[i].click();
        return true;
      }
    }
    return false;
  }

  function doCollect() {
    const result = { recommended_iol: null, result_text: '', table_text: '' };
    const all = document.body.innerText || '';
    const all2 = document.body.textContent || '';
    var combined = all + '\n' + all2;
    var match = combined.match(/Recommended\s*IOL[:\s]*([\d.]+)/i);
    if (!match) match = combined.match(/IOL\s*Power\s*@\s*Emmetropia[^\d]*([\d.]+)/i);
    if (!match) match = combined.match(/Emmetropia\s*[\[\(]?\s*D\s*[\]\)]?\s*[:\s]*([\d.]+)/i);
    if (match) result.recommended_iol = parseFloat(match[1]);
    const textboxes = document.querySelectorAll('input[type="text"], textarea');
    for (let i = 0; i < textboxes.length; i++) {
      const v = (textboxes[i].value || '').trim();
      if (v.indexOf('Recommended IOL') !== -1 || v.indexOf('Emmetropia') !== -1) result.result_text = v;
    }
    var tables = document.querySelectorAll('table');
    for (var ti = 0; ti < tables.length; ti++) {
      var t = tables[ti].innerText || '';
      var hasIol = t.indexOf('IOL Power') !== -1 || t.indexOf('IOL[D]') !== -1 || t.indexOf('IOL ') !== -1;
      var hasRefr = t.indexOf('Refraction') !== -1 || t.indexOf('REFR') !== -1;
      if (hasIol && hasRefr) result.table_text = t;
    }
    if (!result.table_text) {
      var allEls = document.querySelectorAll('div, p, section, span');
      for (var ei = 0; ei < allEls.length; ei++) {
        var txt = (allEls[ei].innerText || allEls[ei].textContent || '').trim();
        if (txt.length > 20 && txt.length < 2000 && (txt.indexOf('Constants: A=') !== -1 || (txt.indexOf('IOL') !== -1 && txt.indexOf('REFR') !== -1))) {
          result.table_text = txt;
          break;
        }
      }
    }
    if (result.recommended_iol == null) {
      var divs = document.querySelectorAll('div, p, span, td, th');
      for (var di = 0; di < divs.length; di++) {
        var txt = (divs[di].innerText || divs[di].textContent || '').trim();
        if (txt.length < 800 && txt.indexOf('Emmetropia') !== -1) {
          var m = txt.match(/Emmetropia[^\d]*([\d.]+)/i) || txt.match(/IOL\s*Power[^\d]*([\d.]+)/i);
          if (m) { result.recommended_iol = parseFloat(m[1]); result.result_text = txt; break; }
        }
      }
    }
    if (result.recommended_iol == null || !result.table_text) {
      var jsonEls = document.querySelectorAll('pre, div');
      for (var ji = 0; ji < jsonEls.length; ji++) {
        var raw = (jsonEls[ji].textContent || '').trim();
        if (raw.length < 200 || raw.length > 6000 || raw.indexOf('calculationResult') === -1) continue;
        if (raw.indexOf('"od"') === -1 && raw.indexOf('"os"') === -1) continue;
        try {
          var data = JSON.parse(raw);
          var cr = (data.od && data.od.calculationResult) || (data.os && data.os.calculationResult);
          if (cr) {
            var iolNum = cr.iolPowerAtEmmetropia != null ? cr.iolPowerAtEmmetropia : (cr.recommendedIol != null ? cr.recommendedIol : (cr.recommendedIOL != null ? cr.recommendedIOL : (cr.emmetropiaIol != null ? cr.emmetropiaIol : null)));
            if (iolNum != null && result.recommended_iol == null) result.recommended_iol = parseFloat(iolNum);
            if (!result.table_text && cr.resultTable) result.table_text = typeof cr.resultTable === 'string' ? cr.resultTable : JSON.stringify(cr.resultTable);
            if (!result.table_text && cr.iolRefrTable) result.table_text = typeof cr.iolRefrTable === 'string' ? cr.iolRefrTable : JSON.stringify(cr.iolRefrTable);
          }
        } catch (e) {}
      }
    }
    var hasData = result.recommended_iol != null || (result.result_text && result.result_text.trim()) || (result.table_text && result.table_text.trim()) || (combined.indexOf('Constants: A=') !== -1);
    result.complete = !!hasData;
    result.reason = hasData ? null : 'Data incomplete (no Recommended IOL or result table)';
    return result;
  }

  if (window !== window.top) {
    window.addEventListener('message', function (ev) {
      if (!ev.data || !ev.data.action) return;
      if (ev.data.action === 'fill') {
        doFill(ev.data.payload, document);
        window.top.postMessage({ _fromRbf: true, ok: true }, '*');
      } else if (ev.data.action === 'clickCalculate') {
        doClickCalculate(document);
        window.top.postMessage({ _fromRbf: true, ok: true }, '*');
      } else if (ev.data.action === 'collect') {
        const r = doCollect();
        window.top.postMessage({
          _fromRbf: true,
          complete: r.complete,
          reason: r.reason,
          recommended_iol: r.recommended_iol,
          result_text: r.result_text,
          table_text: r.table_text
        }, '*');
      }
    });
    return;
  }

  chrome.runtime.onMessage.addListener(function (msg, sender, sendResponse) {
    const iframe = document.querySelector('iframe');
    if (!iframe || !iframe.contentWindow) {
      sendResponse({ error: 'No iframe found' });
      return false;
    }
    const handler = function (ev) {
      if (ev.data && ev.data._fromRbf === true) {
        window.removeEventListener('message', handler);
        sendResponse(ev.data);
      }
    };
    window.addEventListener('message', handler);
    iframe.contentWindow.postMessage({ action: msg.action, payload: msg.payload }, '*');
    return true;
  });

  function injectFloatingPanel() {
    if (document.getElementById('rbf-float-panel')) return;
    const style = document.createElement('style');
    style.textContent = [
      '#rbf-float-panel { position: fixed; top: 50%; right: 12px; transform: translateY(-50%); z-index: 2147483647;',
      'width: 220px; background: #fff; border: 1px solid #ccc; border-radius: 8px; box-shadow: 0 4px 20px rgba(0,0,0,0.2);',
      'font-family: sans-serif; font-size: 13px; padding: 10px; user-select: none; max-height: 90vh; overflow-y: auto; }',
      '#rbf-float-panel.minimized { width: auto; height: auto; padding: 4px; }',
      '#rbf-float-panel.minimized #rbf-float-body { display: none; }',
      '#rbf-float-panel .rbf-drag { cursor: move; padding: 4px 8px; margin: -10px -10px 8px -10px; border-radius: 8px 8px 0 0; background: #e8e8e8; display: flex; justify-content: space-between; align-items: center; }',
      '#rbf-float-panel .rbf-status { color: #666; font-size: 11px; margin: 6px 0; min-height: 32px; }',
      '#rbf-float-panel button, #rbf-float-panel input[type=file] { display: block; width: 100%; margin: 4px 0; padding: 6px 8px; cursor: pointer; }',
      '#rbf-float-panel input[type=file] { font-size: 11px; }',
      '#rbf-float-panel #rbf-btn-min { padding: 2px; margin: 0; width: 28px; height: 28px; }'
    ].join(' ');
    document.head.appendChild(style);
    const panel = document.createElement('div');
    panel.id = 'rbf-float-panel';
    panel.innerHTML = [
      '<div class="rbf-drag" id="rbf-drag"><span>RBF</span><button id="rbf-btn-min" title="Minimize">\(-\)</button></div>',
      '<div id="rbf-float-body">',
      '<input type="file" id="rbf-file" accept=".json" title="Load rbf_pending.json">',
      '<div class="rbf-status" id="rbf-status">Load JSON first</div>',
      '<button id="rbf-fill">Fill</button>',
      '<button id="rbf-calculate">Calculate</button>',
      '<button id="rbf-auto">Auto run</button>',
      '<button id="rbf-stop">Stop auto</button>',
      '<button id="rbf-next">Next</button>',
      '<button id="rbf-force-next">Force next</button>',
      '<button id="rbf-collect">Collect</button>',
      '<button id="rbf-export">Download</button>',
      '</div>'
    ].join('');
    document.body.appendChild(panel);

    let autoRunning = false;
    let autoTimer = null;

    function postToIframe(action, payload, timeoutMs) {
      return new Promise(function (resolve) {
        const iframe = document.querySelector('iframe');
        if (!iframe || !iframe.contentWindow) {
          resolve({ error: 'No iframe' });
          return;
        }
        let done = false;
        const handler = function (ev) {
          if (!ev.data || ev.data._fromRbf !== true) return;
          if (done) return;
          done = true;
          window.removeEventListener('message', handler);
          resolve(ev.data);
        };
        window.addEventListener('message', handler);
        iframe.contentWindow.postMessage({ action: action, payload: payload }, '*');
        setTimeout(function () {
          if (done) return;
          done = true;
          window.removeEventListener('message', handler);
          resolve({ error: 'timeout', complete: false });
        }, timeoutMs || 8000);
      });
    }

    function sleep(ms) {
      return new Promise(function (resolve) { setTimeout(resolve, ms); });
    }

    async function autoCollectAndAdvance() {
      const scraped = await postToIframe('collect', null, 5000);
      if (!scraped || scraped.complete === false || scraped.error) {
        return false;
      }
      return new Promise(function (resolve) {
        chrome.storage.local.get(['pendingList', 'currentIndex', 'results'], function (d) {
          const list = d.pendingList || [];
          const idx = d.currentIndex != null ? d.currentIndex : 0;
          const res = d.results || [];
          const item = list[idx];
          if (!item) {
            resolve(false);
            return;
          }
          res.push({
            id: item && item.id,
            eye: item && item.eye,
            row_index: item && item.row_index,
            recommended_iol: scraped.recommended_iol,
            result_text: scraped.result_text,
            table_text: scraped.table_text
          });
          chrome.storage.local.set({ currentIndex: idx + 1, results: res }, function () {
            updateStatus('Auto collected ' + (item.id || '') + ' ' + (item.eye || '') + ' | total ' + res.length);
            resolve(true);
          });
        });
      });
    }

    async function autoFillCurrent() {
      return new Promise(function (resolve) {
        chrome.storage.local.get(['pendingList', 'currentIndex'], function (d) {
          const list = d.pendingList || [];
          const idx = d.currentIndex != null ? d.currentIndex : 0;
          if (idx >= list.length) {
            updateStatus('Auto done: all samples finished');
            resolve(null);
            return;
          }
          const payload = list[idx];
          postToIframe('fill', payload, 3000).then(function () {
            updateStatus('Auto fill ' + (idx + 1) + '/' + list.length + ' ' + (payload.id || '') + ' ' + (payload.eye || ''));
            resolve(payload);
          });
        });
      });
    }

    async function autoLoopOnce() {
      if (!autoRunning) return;
      const payload = await autoFillCurrent();
      if (!payload) {
        autoRunning = false;
        return;
      }
      await sleep(1800);
      if (!autoRunning) return;
      await postToIframe('clickCalculate', null, 3000);
      updateStatus('Auto: solve reCAPTCHA if shown, waiting for result...');
      const deadline = Date.now() + 180000;
      while (autoRunning && Date.now() < deadline) {
        await sleep(2500);
        if (!autoRunning) return;
        const ok = await autoCollectAndAdvance();
        if (ok) {
          await sleep(1200);
          if (autoRunning) autoLoopOnce();
          return;
        }
      }
      if (autoRunning) {
        updateStatus('Auto timeout on current sample. Click Force next or retry Auto.');
        autoRunning = false;
      }
    }

    let dragStart = null;
    document.getElementById('rbf-drag').addEventListener('mousedown', function (e) {
      if (e.target.id === 'rbf-btn-min') return;
      const rect = panel.getBoundingClientRect();
      dragStart = { x: e.clientX - rect.left, y: e.clientY - rect.top };
    });
    document.addEventListener('mousemove', function (e) {
      if (!dragStart) return;
      panel.style.left = (e.clientX - dragStart.x) + 'px';
      panel.style.top = (e.clientY - dragStart.y) + 'px';
      panel.style.right = 'auto';
      panel.style.transform = 'none';
    });
    document.getElementById('rbf-btn-min').addEventListener('mousedown', function (e) { e.stopPropagation(); });
    document.addEventListener('mouseup', function () { dragStart = null; });

    document.getElementById('rbf-btn-min').addEventListener('click', function () {
      panel.classList.toggle('minimized');
    });

    function updateStatus(msg) {
      chrome.storage.local.get(['pendingList', 'currentIndex', 'results'], function (d) {
        const list = d.pendingList || [];
        const idx = d.currentIndex != null ? d.currentIndex : 0;
        const res = d.results || [];
        const el = document.getElementById('rbf-status');
        if (msg !== undefined) { el.textContent = msg; return; }
        if (list.length === 0) el.textContent = 'Load JSON first';
        else el.textContent = 'Sample ' + (idx + 1) + ' / ' + list.length + ' | Collected: ' + res.length;
      });
    }

    document.getElementById('rbf-file').addEventListener('change', function (e) {
      const f = e.target.files && e.target.files[0];
      if (!f) return;
      const r = new FileReader();
      r.onload = function () {
        try {
          const arr = JSON.parse(r.result);
          if (!Array.isArray(arr)) throw new Error('JSON must be array');
          chrome.storage.local.set({ pendingList: arr, currentIndex: 0, results: [] }, updateStatus);
        } catch (err) {
          document.getElementById('rbf-status').textContent = 'Error: ' + err.message;
        }
      };
      r.readAsText(f, 'UTF-8');
    });

    document.getElementById('rbf-fill').addEventListener('click', function () {
      chrome.storage.local.get(['pendingList', 'currentIndex'], function (d) {
        const list = d.pendingList || [];
        const idx = d.currentIndex != null ? d.currentIndex : 0;
        if (idx >= list.length) { updateStatus('No more samples'); return; }
        const payload = list[idx];
        const iframe = document.querySelector('iframe');
        if (iframe && iframe.contentDocument) {
          try {
            doFill(payload, iframe.contentDocument);
            updateStatus('Filled ' + (payload.id || '') + ' ' + (payload.eye || ''));
          } catch (err) { updateStatus('Error: ' + err.message); }
          return;
        }
        if (iframe && iframe.contentWindow) {
          const handler = function (ev) {
            if (ev.data && ev.data._fromRbf === true) {
              window.removeEventListener('message', handler);
              updateStatus('Filled ' + (payload.id || '') + ' ' + (payload.eye || ''));
            }
          };
          window.addEventListener('message', handler);
          iframe.contentWindow.postMessage({ action: 'fill', payload: payload }, '*');
          return;
        }
        updateStatus('No iframe found');
      });
    });

    document.getElementById('rbf-calculate').addEventListener('click', function () {
      const iframe = document.querySelector('iframe');
      if (iframe && iframe.contentDocument) {
        try {
          if (doClickCalculate(iframe.contentDocument)) updateStatus('Calculate clicked (complete reCAPTCHA)');
          else updateStatus('Calculate button not found');
        } catch (err) { updateStatus('Error: ' + err.message); }
        return;
      }
      if (iframe && iframe.contentWindow) {
        const handler = function (ev) {
          if (ev.data && ev.data._fromRbf === true) {
            window.removeEventListener('message', handler);
            updateStatus('Calculate clicked (complete reCAPTCHA)');
          }
        };
        window.addEventListener('message', handler);
        iframe.contentWindow.postMessage({ action: 'clickCalculate' }, '*');
        updateStatus('Calculate sent (complete reCAPTCHA)');
        return;
      }
      updateStatus('No iframe found');
    });

    document.getElementById('rbf-auto').addEventListener('click', function () {
      if (autoRunning) {
        updateStatus('Auto already running');
        return;
      }
      chrome.storage.local.get(['pendingList'], function (d) {
        if (!(d.pendingList || []).length) {
          updateStatus('Load JSON first');
          return;
        }
        autoRunning = true;
        updateStatus('Auto started (fill -> calculate -> wait captcha/result -> collect -> next)');
        autoLoopOnce();
      });
    });

    document.getElementById('rbf-stop').addEventListener('click', function () {
      autoRunning = false;
      if (autoTimer) {
        clearTimeout(autoTimer);
        autoTimer = null;
      }
      updateStatus('Auto stopped');
    });

    document.getElementById('rbf-next').addEventListener('click', function () {
      chrome.storage.local.get(['pendingList', 'currentIndex'], function (d) {
        const list = d.pendingList || [];
        var idx = d.currentIndex != null ? d.currentIndex : 0;
        idx++;
        if (idx >= list.length) { updateStatus('No more samples'); return; }
        chrome.storage.local.set({ currentIndex: idx }, function () {
          const payload = list[idx];
          const iframe = document.querySelector('iframe');
          if (iframe && iframe.contentDocument) {
            try {
              doFill(payload, iframe.contentDocument);
              updateStatus();
            } catch (err) { updateStatus('Error: ' + err.message); }
            return;
          }
          if (iframe && iframe.contentWindow) {
            const handler = function (ev) {
              if (ev.data && ev.data._fromRbf === true) {
                window.removeEventListener('message', handler);
                updateStatus();
              }
            };
            window.addEventListener('message', handler);
            iframe.contentWindow.postMessage({ action: 'fill', payload: payload }, '*');
            updateStatus();
            return;
          }
          updateStatus('No iframe found');
        });
      });
    });

    document.getElementById('rbf-force-next').addEventListener('click', function () {
      chrome.storage.local.get(['pendingList', 'currentIndex'], function (d) {
        const list = d.pendingList || [];
        var idx = d.currentIndex != null ? d.currentIndex : 0;
        idx++;
        if (idx >= list.length) { updateStatus('No more samples'); return; }
        chrome.storage.local.set({ currentIndex: idx }, function () {
          const payload = list[idx];
          const iframe = document.querySelector('iframe');
          if (iframe && iframe.contentDocument) {
            try {
              doFill(payload, iframe.contentDocument);
              updateStatus();
            } catch (err) { updateStatus('Error: ' + err.message); }
            return;
          }
          if (iframe && iframe.contentWindow) {
            const handler = function (ev) {
              if (ev.data && ev.data._fromRbf === true) {
                window.removeEventListener('message', handler);
                updateStatus();
              }
            };
            window.addEventListener('message', handler);
            iframe.contentWindow.postMessage({ action: 'fill', payload: payload }, '*');
            updateStatus();
            return;
          }
          updateStatus('No iframe found');
        });
      });
    });

    document.getElementById('rbf-collect').addEventListener('click', function () {
      const iframe = document.querySelector('iframe');
      if (!iframe || !iframe.contentWindow) {
        updateStatus('No iframe');
        return;
      }
      const handler = function (ev) {
        if (!ev.data || ev.data._fromRbf !== true) return;
        window.removeEventListener('message', handler);
        if (ev.data.complete === false) {
          updateStatus('Collect failed: ' + (ev.data.reason || 'data incomplete'));
          return;
        }
        chrome.storage.local.get(['pendingList', 'currentIndex', 'results'], function (d) {
          const list = d.pendingList || [];
          const idx = d.currentIndex != null ? d.currentIndex : 0;
          const res = d.results || [];
          const item = list[idx];
          res.push({
            id: item && item.id,
            eye: item && item.eye,
            row_index: item && item.row_index,
            recommended_iol: ev.data.recommended_iol,
            result_text: ev.data.result_text,
            table_text: ev.data.table_text
          });
          chrome.storage.local.set({ currentIndex: idx + 1, results: res }, updateStatus);
        });
      };
      window.addEventListener('message', handler);
      iframe.contentWindow.postMessage({ action: 'collect' }, '*');
    });

    document.getElementById('rbf-export').addEventListener('click', function () {
      chrome.storage.local.get('results', function (d) {
        const res = d.results || [];
        if (res.length === 0) {
          document.getElementById('rbf-status').textContent = 'No results';
          return;
        }
        const blob = new Blob([JSON.stringify(res, null, 2)], { type: 'application/json' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'rbf_results.json';
        a.click();
        URL.revokeObjectURL(a.href);
        document.getElementById('rbf-status').textContent = 'Downloaded ' + res.length + ' rows';
      });
    });

    updateStatus();
  }

  if (window === window.top && /rbfcalculator\.com/.test(window.location.hostname)) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', injectFloatingPanel);
    } else {
      injectFloatingPanel();
    }
  }
})();
