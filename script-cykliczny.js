document.addEventListener('DOMContentLoaded', async () => {
    // --- ODWOŁANIA DO ELEMENTÓW DOM ---
    const invalidLinkContainer = document.getElementById('invalidLinkContainer');
    const bookingContainer = document.getElementById('bookingContainer');
    const reservationForm = document.getElementById('reservationForm');
    const reserveButton = document.getElementById('reserveButton');
    const reservationStatus = document.getElementById('reservationStatus');
    const calendarContainer = document.getElementById('calendar-container');
    const mobileContainer = document.getElementById('calendar-mobile-container');
    
    // Pola formularza
    const firstNameInput = document.getElementById('firstName');
    const lastNameInput = document.getElementById('lastName');
    const subjectSelect = document.getElementById('subject');
    const schoolTypeSelect = document.getElementById('schoolType');
    
    // Grupy warunkowe
    const classGroup = document.getElementById('classGroup');
    const schoolClassSelect = document.getElementById('schoolClass');
    const levelGroup = document.getElementById('levelGroup');
    const schoolLevelSelect = document.getElementById('schoolLevel');
    
    // Checkboxy i Wybór Tutora
    const chooseTutorCheckbox = document.getElementById('chooseTutorCheckbox');
    const tutorGroup = document.getElementById('tutorGroup');
    const tutorSelect = document.getElementById('tutorSelect');
    const isOneTimeCheckbox = document.getElementById('isOneTimeCheckbox');
    
    // Polityka prywatności (checkbox removed)
    // const termsCheckboxCyclic = document.getElementById('termsCheckboxCyclic');
    
    const baseFormFields = [subjectSelect, schoolTypeSelect];
    let clientID = null;

    // --- KONFIGURACJA ---
    const API_BASE_URL = 'https://zakręcone-korepetycje.pl'; 

    // --- ZMIENNE STANU ---
    let selectedSlotId = null;
    let selectedDate = null;
    let selectedTime = null;
    let currentWeekStart = getMonday(new Date());
    let availableSlotsData = {};

    const monthNames = ["Styczeń", "Luty", "Marzec", "Kwiecień", "Maj", "Czerwiec", "Lipiec", "Sierpień", "Wrzesień", "Październik", "Listopad", "Grudzień"];
    const dayNamesFull = ["Niedziela", "Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota"];
    const workingHoursStart = 8;
    const workingHoursEnd = 22;
    
    const schoolClasses = {
        'szkola_podstawowa': ['4', '5', '6', '7', '8'],
        'liceum': ['1', '2', '3', '4'],
        'technikum': ['1', '2', '3', '4', '5']
    };

    // --- INICJALIZACJA APLIKACJI ---
    async function initializeApp() {
        const params = new URLSearchParams(window.location.search);
        clientID = params.get('clientID');

        if (!clientID) {
            displayInvalidLinkError();
            return;
        }

        try {
            const clientData = await verifyClient(clientID);
            prepareBookingForm(clientData);
            
            // Najpierw ustawiamy event listenery
            initializeEventListeners();
            
            // Potem inicjalizujemy stan formularza
            updateSchoolDependentFields();
            handleTutorSelection();
            
            // Na końcu pobieramy dane
            fetchAvailableSlots(currentWeekStart);
        } catch (error) {
            console.error(error);
            displayInvalidLinkError(error.message);
        }
    }

    function displayInvalidLinkError(message = "Nieprawidłowy link. Skontaktuj się z obsługą klienta.") {
        if(bookingContainer) bookingContainer.style.display = 'none';
        if(invalidLinkContainer) {
            invalidLinkContainer.style.display = 'block';
            const p = invalidLinkContainer.querySelector('p');
            if (p && message) p.textContent += ` (${message})`;
        }
    }

    async function verifyClient(id) {
        const apiUrl = `${API_BASE_URL}/api/verify-client?clientID=${id}`;
        const response = await fetch(apiUrl);
        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.message || "Nie udało się zweryfikować klienta.");
        }
        return await response.json();
    }

    function prepareBookingForm(clientData) {
        firstNameInput.value = clientData.firstName || '';
        lastNameInput.value = clientData.lastName || '';
        bookingContainer.style.display = 'flex';
    }

    // --- FUNKCJE LOGIKI ---

    function getMonday(d) {
        d = new Date(d);
        const day = d.getDay();
        const diff = d.getDate() - day + (day === 0 ? -6 : 1);
        return new Date(d.setDate(diff));
    }
    
    function getFormattedDate(date) {
        const yyyy = date.getFullYear();
        const mm = String(date.getMonth() + 1).padStart(2, '0');
        const dd = String(date.getDate()).padStart(2, '0');
        return `${yyyy}-${mm}-${dd}`;
    }

    function showStatus(message, type) {
        reservationStatus.textContent = message;
        reservationStatus.className = `reservation-status ${type}`;
        reservationStatus.style.display = 'block';
        setTimeout(() => {
            reservationStatus.style.display = 'none';
        }, 5000);
    }

    // --- WALIDACJA FORMULARZA ---
    function checkFormValidity() {
        // 1. Sprawdź pola podstawowe (selecty)
        const isBaseFormValid = baseFormFields.every(field => field.checkValidity());
        
        // 2. Sprawdź imię i nazwisko (pola tekstowe required)
        const isNameValid = firstNameInput.value.trim() !== "" && lastNameInput.value.trim() !== "";

        // 3. Sprawdź pola warunkowe (klasa/poziom)
        let isClassValid = classGroup.style.display === 'none' || schoolClassSelect.checkValidity();
        let isLevelValid = levelGroup.style.display === 'none' || schoolLevelSelect.checkValidity();
        
        // 4. Sprawdź tutora
        let isTutorValid = tutorGroup.style.display === 'none' || (tutorSelect.value !== "");
        
        // 5. Sprawdź czy wybrano termin w kalendarzu
        let isSlotSelected = selectedSlotId !== null;

        // Logowanie dla celów diagnostycznych (możesz usunąć po wdrożeniu)
        // console.log("Walidacja:", {
        //     base: isBaseFormValid,
        //     names: isNameValid,
        //     class: isClassValid,
        //     level: isLevelValid,
        //     tutor: isTutorValid,
        //     slot: isSlotSelected
        // });

        reserveButton.disabled = !(isBaseFormValid && isNameValid && isClassValid && isLevelValid && isTutorValid && isSlotSelected);
    }

    // --- OBSŁUGA UI FORMULARZA ---
    function updateSchoolDependentFields() {
        const selectedSchoolType = schoolTypeSelect.value;
        schoolClassSelect.innerHTML = '<option value="">Wybierz klasę</option>';
        
        if (selectedSchoolType in schoolClasses) {
            classGroup.style.display = 'block';
            schoolClasses[selectedSchoolType].forEach(cls => {
                const option = document.createElement('option');
                option.value = cls;
                option.textContent = cls;
                schoolClassSelect.appendChild(option);
            });
            schoolClassSelect.required = true;
        } else {
            classGroup.style.display = 'none';
            schoolClassSelect.required = false;
        }
        
        if (selectedSchoolType === 'liceum' || selectedSchoolType === 'technikum') {
            levelGroup.style.display = 'block';
            schoolLevelSelect.required = true;
        } else {
            levelGroup.style.display = 'none';
            schoolLevelSelect.required = false;
            schoolLevelSelect.value = '';
        }
    }
    
    function handleTutorSelection() {
        if (chooseTutorCheckbox.checked) {
            tutorGroup.style.display = 'block';
            tutorSelect.required = true;
        } else {
            tutorGroup.style.display = 'none';
            tutorSelect.required = false;
            tutorSelect.value = '';
        }
        // Po zmianie wyboru tutora, odśwież sloty
        fetchAvailableSlots(currentWeekStart);
        checkFormValidity();
    }
    
    function updateTutorList(newTutors) {
        const currentTutorsInSelect = Array.from(tutorSelect.options).map(o => o.value).filter(v => v);
        // Proste sprawdzenie czy lista się zmieniła
        if (JSON.stringify(newTutors.sort()) === JSON.stringify(currentTutorsInSelect.sort())) return;
        
        // Zachowaj obecny wybór jeśli jest na nowej liście
        const currentSelection = tutorSelect.value;
        
        tutorSelect.innerHTML = '<option value="">Wybierz korepetytora</option>';
        newTutors.forEach(tutor => {
            const option = document.createElement('option');
            option.value = tutor;
            option.textContent = tutor;
            tutorSelect.appendChild(option);
        });

        if (newTutors.includes(currentSelection)) {
            tutorSelect.value = currentSelection;
        }
    }

    // --- KALENDARZ ---
    function selectSlot(slotId, element, date, time) {
        const prevSelected = document.querySelectorAll('.time-block.selected');
        prevSelected.forEach(block => block.classList.remove('selected'));
        
        const allMatchingBlocks = document.querySelectorAll(`[data-slot-id="${slotId}"]`);
        allMatchingBlocks.forEach(block => block.classList.add('selected'));

        selectedSlotId = slotId;
        selectedDate = date;
        selectedTime = time;
        checkFormValidity();
    }
    
    function changeWeek(days) {
        currentWeekStart.setDate(currentWeekStart.getDate() + days);
        selectedSlotId = null;
        selectedDate = null;
        selectedTime = null;
        checkFormValidity();
        fetchAvailableSlots(currentWeekStart);
    }

    function renderCalendarViews(startDate) {
        // Wyczyść kontenery
        calendarContainer.innerHTML = '';
        calendarContainer.className = 'time-slot-calendar';
        if (mobileContainer) mobileContainer.innerHTML = '';

        generatePCGridCalendar(startDate);
        generateMobileListCalendar(startDate);

        // Obsługa przycisków
        const pcPrev = calendarContainer.querySelector('#prevWeek');
        const pcNext = calendarContainer.querySelector('#nextWeek');
        if (pcPrev) pcPrev.addEventListener('click', () => changeWeek(-7));
        if (pcNext) pcNext.addEventListener('click', () => changeWeek(7));

        if (mobileContainer) {
            const mobilePrev = mobileContainer.querySelector('#mobilePrevWeek');
            const mobileNext = mobileContainer.querySelector('#mobileNextWeek');
            if (mobilePrev) mobilePrev.addEventListener('click', () => changeWeek(-7));
            if (mobileNext) mobileNext.addEventListener('click', () => changeWeek(7));
        }
    }

    function generatePCGridCalendar(startDate) {
        const daysInWeek = Array.from({length: 7}, (_, i) => {
            const d = new Date(startDate);
            d.setDate(d.getDate() + i);
            return d;
        });
    
        const calendarNavigation = document.createElement('div');
        calendarNavigation.className = 'calendar-navigation';
        const firstDayFormatted = `${dayNamesFull[daysInWeek[0].getDay()].substring(0,3)}. ${daysInWeek[0].getDate()} ${monthNames[daysInWeek[0].getMonth()].substring(0,3)}.`;
        const lastDayFormatted = `${dayNamesFull[daysInWeek[6].getDay()].substring(0,3)}. ${daysInWeek[6].getDate()} ${monthNames[daysInWeek[6].getMonth()].substring(0,3)}.`;
        calendarNavigation.innerHTML = `
            <button id="prevWeek" type="button">Poprzedni tydzień</button>
            <h3>${firstDayFormatted} - ${lastDayFormatted}</h3>
            <button id="nextWeek" type="button">Następny tydzień</button>
        `;
        calendarContainer.appendChild(calendarNavigation);
    
        const table = document.createElement('table');
        table.className = 'calendar-grid-table';
        let headerRow = '<tr><th class="time-label">Godzina</th>';
        daysInWeek.forEach(day => {
            headerRow += `<th>${dayNamesFull[day.getDay()]}<br>${String(day.getDate()).padStart(2, '0')} ${monthNames[day.getMonth()].substring(0, 3)}</th>`;
        });
        headerRow += '</tr>';
        table.createTHead().innerHTML = headerRow;
        
        const tbody = table.createTBody();
        
        let currentTime = new Date(startDate);
        currentTime.setHours(workingHoursStart, 0, 0, 0);
        const endTime = new Date(startDate);
        endTime.setHours(workingHoursEnd, 0, 0, 0);
    
        const twelveHoursFromNow = new Date();
        twelveHoursFromNow.setHours(twelveHoursFromNow.getHours() + 12);
    
        while (currentTime < endTime) {
            const timeSlot = currentTime.toTimeString().substring(0, 5);
            const row = tbody.insertRow();
            row.insertCell().outerHTML = `<td class="time-label">${timeSlot}</td>`;
            
            daysInWeek.forEach(day => {
                const cell = row.insertCell();
                const formattedDate = getFormattedDate(day);
                // Tworzymy ID bez tutora na razie do grupowania
                const baseBlockId = `block_${formattedDate}_${timeSlot.replace(':', '')}`;
                
                const daySlots = availableSlotsData[formattedDate] || [];
                const matchingSlots = daySlots.filter(slot => slot.time === timeSlot);
                
                // Jeśli mamy sloty, tworzymy element
                if (matchingSlots.length > 0) {
                    // Jeśli wybrano konkretnego tutora, to już API przefiltrowało.
                    // Tutaj po prostu bierzemy pierwszy, bo w siatce pokazujemy dostępność.
                    // ID slotu zawiera datę i godzinę, co pozwala zaznaczyć go w widoku mobilnym i PC
                    const slotData = matchingSlots[0];
                    
                    const block = document.createElement('div');
                    block.className = 'time-block';
                    block.dataset.slotId = baseBlockId; 
                    block.dataset.date = formattedDate;
                    block.dataset.time = timeSlot;
                    
                    const blockDateTime = new Date(`${formattedDate}T${timeSlot}:00`);
                    let isClickable = false;

                    if (blockDateTime > twelveHoursFromNow) {
                        block.textContent = timeSlot;
                        isClickable = true;
                    } else {
                        block.classList.add('disabled');
                        block.textContent = timeSlot;
                        block.title = "Mniej niż 12h do zajęć.";
                    }
        
                    if(selectedSlotId === baseBlockId) {
                        block.classList.add('selected');
                    }
                    
                    if(isClickable) {
                        block.addEventListener('click', (e) => selectSlot(baseBlockId, e.target, formattedDate, timeSlot));
                    }
                    cell.appendChild(block);
                }
            });
    
            currentTime.setMinutes(currentTime.getMinutes() + 70);
        }
        
        calendarContainer.appendChild(table);
    }

    function generateMobileListCalendar(startDate) {
        if (!mobileContainer) return;

        const daysInWeek = Array.from({length: 7}, (_, i) => {
            const d = new Date(startDate);
            d.setDate(d.getDate() + i);
            return d;
        });

        const calendarNavigation = document.createElement('div');
        calendarNavigation.className = 'calendar-navigation';
        const firstDayFormatted = `${dayNamesFull[daysInWeek[0].getDay()].substring(0,3)}. ${daysInWeek[0].getDate()} ${monthNames[daysInWeek[0].getMonth()].substring(0,3)}.`;
        const lastDayFormatted = `${dayNamesFull[daysInWeek[6].getDay()].substring(0,3)}. ${daysInWeek[6].getDate()} ${monthNames[daysInWeek[6].getMonth()].substring(0,3)}.`;
        calendarNavigation.innerHTML = `
            <button id="mobilePrevWeek" type="button">Poprzedni tydzień</button>
            <h3>${firstDayFormatted} - ${lastDayFormatted}</h3>
            <button id="mobileNextWeek" type="button">Następny tydzień</button>
        `;
        mobileContainer.appendChild(calendarNavigation);

        const twelveHoursFromNow = new Date();
        twelveHoursFromNow.setHours(twelveHoursFromNow.getHours() + 12);
        let hasAvailableSlots = false;

        daysInWeek.forEach(day => {
            const formattedDate = getFormattedDate(day);
            const daySlots = availableSlotsData[formattedDate] || [];
            
            // Filtrowanie unikalnych godzin dla danego dnia
            const uniqueTimes = [...new Set(daySlots.map(item => item.time))];
            
            const availableDaySlots = uniqueTimes.filter(time => {
                const blockDateTime = new Date(`${formattedDate}T${time}:00`);
                return blockDateTime > twelveHoursFromNow;
            });

            if (availableDaySlots.length === 0) return;
            hasAvailableSlots = true;

            const dayCard = document.createElement('div');
            dayCard.className = 'mobile-day-card';
            dayCard.innerHTML = `<h4>${dayNamesFull[day.getDay()]} ${day.getDate()} ${monthNames[day.getMonth()]}</h4>`;
            
            const slotsContainer = document.createElement('div');
            slotsContainer.className = 'mobile-slots-container';

            availableDaySlots.sort();

            availableDaySlots.forEach(time => {
                const baseBlockId = `block_${formattedDate}_${time.replace(':', '')}`;
                const isCurrentlySelected = selectedSlotId === baseBlockId;

                const block = document.createElement('div');
                block.className = `time-block ${isCurrentlySelected ? 'selected' : ''}`;
                block.dataset.slotId = baseBlockId;
                block.dataset.date = formattedDate;
                block.dataset.time = time;
                block.textContent = time;

                block.addEventListener('click', (e) => selectSlot(baseBlockId, e.target, formattedDate, time));
                slotsContainer.appendChild(block);
            });

            dayCard.appendChild(slotsContainer);
            mobileContainer.appendChild(dayCard);
        });

        if (!hasAvailableSlots) {
            const noSlotsMsg = document.createElement('div');
            noSlotsMsg.innerHTML = '<p style="padding: 2rem; text-align: center; color: var(--text-medium);">Brak dostępnych terminów w tym tygodniu.</p>';
            mobileContainer.appendChild(noSlotsMsg);
        }
    }

    async function fetchAvailableSlots(startDate) {
        const selectedSchoolType = schoolTypeSelect.value;
        const selectedLevel = schoolLevelSelect.value;
        const selectedSubject = subjectSelect.value;
        const selectedTutorName = chooseTutorCheckbox.checked ? tutorSelect.value : "";
        
        // Jeśli brakuje podstawowych danych, wyczyść kalendarz
        if (!selectedSchoolType || !selectedSubject || (levelGroup.style.display === 'block' && !selectedLevel)) {
            const placeholder = '<div class="calendar-placeholder"><p style="padding: 2rem; text-align: center; color: var(--text-medium);">Proszę wybrać przedmiot, typ szkoły i poziom, aby zobaczyć dostępne terminy.</p></div>';
            calendarContainer.innerHTML = placeholder;
            if (mobileContainer) mobileContainer.innerHTML = placeholder;
            availableSlotsData = {};
            if (!chooseTutorCheckbox.checked) updateTutorList([]);
            return;
        }

        const loadingHTML = '<div class="calendar-placeholder"><p style="padding: 2rem; text-align: center; color: var(--text-medium);">Ładowanie dostępnych terminów...</p></div>';
        calendarContainer.innerHTML = loadingHTML;
        if (mobileContainer) mobileContainer.innerHTML = loadingHTML;
        
        try {
            const params = new URLSearchParams({
                startDate: getFormattedDate(startDate),
                schoolType: selectedSchoolType,
                schoolLevel: selectedLevel || '',
                subject: selectedSubject
            });

            if (selectedTutorName) {
                params.append('tutorName', selectedTutorName);
            }
            
            const response = await fetch(`${API_BASE_URL}/api/get-schedule?${params.toString()}`);
            if (!response.ok) { throw new Error('Błąd pobierania danych z serwera'); }
            const scheduleFromApi = await response.json();
            
            const processedData = {};
            const uniqueTutors = new Set();
            
            scheduleFromApi.forEach(slot => {
                const { date, time, tutor } = slot;
                if (!processedData[date]) { processedData[date] = []; }
                // Przechowujemy sloty. Tutaj ID może być proste, bo selekcja jest po dacie+godzinie
                processedData[date].push({ time: time, tutor: tutor });
                uniqueTutors.add(tutor);
            });
            availableSlotsData = processedData;
            
            // Aktualizuj listę tutorów tylko jeśli nie wybrano konkretnego (żeby nie zresetować wyboru)
            // lub jeśli lista jest pusta
            if (!chooseTutorCheckbox.checked || tutorSelect.options.length <= 1) {
                updateTutorList(Array.from(uniqueTutors));
            }

            renderCalendarViews(startDate);

        } catch (error) {
            console.error('Nie udało się pobrać grafiku:', error);
            showStatus('Błąd ładowania grafiku. Spróbuj ponownie później.', 'error');
        }
    }
    
    // --- EVENT LISTENERS ---
    function initializeEventListeners() {
        // 1. Zmiany w polach formularza
        reservationForm.addEventListener('change', (event) => {
            const targetId = event.target.id;
            
            if (['subject', 'schoolType', 'schoolLevel'].includes(targetId)) {
                if (targetId === 'schoolType') {
                    updateSchoolDependentFields();
                }
                // Resetujemy slot po zmianie parametrów
                selectedSlotId = null;
                fetchAvailableSlots(currentWeekStart);
            } 
            else if (targetId === 'chooseTutorCheckbox') {
                handleTutorSelection();
            }
            else if (targetId === 'tutorSelect') {
                // Po wyborze tutora odśwież sloty (API przefiltruje pod tutora)
                fetchAvailableSlots(currentWeekStart);
            }
            
            checkFormValidity();
        });
        
        // 2. Input tekstu
        reservationForm.addEventListener('input', checkFormValidity);
        
        // Privacy policy checkbox removed - no longer needed

        // 4. Przycisk Rezerwacji
        reserveButton.addEventListener('click', async (e) => {
            e.preventDefault();
            checkFormValidity(); // Upewnij się jeszcze raz
            
            if (reserveButton.disabled) {
                // To teoretycznie nie powinno się wykonać, jeśli button jest disabled, ale dla bezpieczeństwa
                showStatus('Proszę uzupełnić formularz.', 'error');
                return;
            }
        
            const formData = {
                clientID: clientID,
                firstName: firstNameInput.value, 
                lastName: lastNameInput.value, 
                subject: subjectSelect.value,
                schoolType: schoolTypeSelect.value,
                schoolLevel: levelGroup.style.display === 'block' ? schoolLevelSelect.value : null,
                schoolClass: classGroup.style.display === 'block' ? schoolClassSelect.value : null,
                tutor: chooseTutorCheckbox.checked ? tutorSelect.value : "Dowolny dostępny",
                selectedDate: selectedDate, 
                selectedTime: selectedTime,
                privacyPolicyAccepted: true  // Automatyczna akceptacja
            };
            
            if (isOneTimeCheckbox) {
                formData.isOneTime = isOneTimeCheckbox.checked;
            }
        
            reserveButton.disabled = true;
            reserveButton.textContent = 'Rezerwuję...';
            showStatus('Trwa rezerwacja...', 'info');
            
            try {
                const response = await fetch(`${API_BASE_URL}/api/create-reservation`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(formData),
                });
                
                if (response.ok) {
                    const result = await response.json();
                    
                    const params = new URLSearchParams({
                        date: formData.selectedDate,
                        time: formData.selectedTime,
                        teamsUrl: encodeURIComponent(result.teamsUrl || ''),
                        token: result.managementToken || '',
                        clientID: result.clientID || '',
                        isCyclic: result.isCyclic,
                        isTest: result.isTest
                    });
                    // Przekierowanie
                    window.location.href = `confirmation.html?${params.toString()}`;
                } else {
                    const errorData = await response.json().catch(() => ({ error: 'Nieznany błąd' }));
                    showStatus(errorData.message || errorData.error || `Błąd rezerwacji: ${response.statusText}`, 'error');
                    reserveButton.disabled = false;
                    reserveButton.textContent = 'Zarezerwuj termin';
                }
            } catch (error) {
                console.error('Błąd rezerwacji:', error);
                showStatus('Wystąpił błąd połączenia z serwerem.', 'error');
                reserveButton.disabled = false;
                reserveButton.textContent = 'Zarezerwuj termin';
            }
        });
    }

    // --- START ---
    initializeApp();
});
