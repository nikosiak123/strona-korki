document.addEventListener('DOMContentLoaded', async () => {
    // Odwołania do elementów
    const invalidLinkContainer = document.getElementById('invalidLinkContainer');
    const bookingContainer = document.getElementById('bookingContainer');
    const reservationForm = document.getElementById('reservationForm');
    const reserveButton = document.getElementById('reserveButton');
    const reservationStatus = document.getElementById('reservationStatus');
    const calendarContainer = document.getElementById('calendar-container');
    const firstNameInput = document.getElementById('firstName');
    const lastNameInput = document.getElementById('lastName');
    const subjectSelect = document.getElementById('subject');
    const schoolTypeSelect = document.getElementById('schoolType');
    const classGroup = document.getElementById('classGroup');
    const schoolClassSelect = document.getElementById('schoolClass');
    const levelGroup = document.getElementById('levelGroup');
    const schoolLevelSelect = document.getElementById('schoolLevel');
    const chooseTutorCheckbox = document.getElementById('chooseTutorCheckbox');
    const tutorGroup = document.getElementById('tutorGroup');
    const tutorSelect = document.getElementById('tutorSelect');
    const termsCheckbox = document.getElementById('termsCheckbox');
    const lessonPriceSpan = document.getElementById('lessonPrice');
    
    // Lista pól do podstawowej walidacji
    const baseFormFields = [subjectSelect, schoolTypeSelect];
    let clientID = null;

    const API_BASE_URL = 'https://zakręcone-korepetycje.pl'; // Zmień na adres z Cloud Run przy wdrożeniu

    // --- FUNKCJA OBLICZANIA CENY ---
    function calculateAndDisplayPrice() {
        const schoolType = schoolTypeSelect.value;
        const schoolLevel = schoolLevelSelect.value;
        // Na stronie testowej nie ma `schoolClassSelect`, więc sprawdzamy, czy istnieje
        const schoolClass = schoolClassSelect ? schoolClassSelect.value : null; 
        
        let price = 0;

        if (schoolType === 'szkola_podstawowa') {
            price = 65;
        } else if (schoolClass && schoolClass.toLowerCase().includes('matura')) {
            price = 80;
        } else if (schoolLevel === 'rozszerzony') {
            price = 75;
        } else if (schoolType === 'liceum' || schoolType === 'technikum') {
            // Domyślna cena dla liceum/technikum (poziom podstawowy)
            price = 70;
        }

        if (price > 0) {
            lessonPriceSpan.textContent = price;
        } else {
            lessonPriceSpan.textContent = '...';
        }
    }

    // --- GŁÓWNA LOGIKA INICJALIZACJI APLIKACJI ---
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
            initializeEventListeners();
            updateSchoolDependentFields();
            handleTutorSelection();
            fetchAvailableSlots(currentWeekStart);
        } catch (error) {
            displayInvalidLinkError(error.message);
        }
    }

    function displayInvalidLinkError(message = "Nieprawidłowy link. Skontaktuj się z obsługą klienta, aby otrzymać swój osobisty link do rezerwacji.") {
        if(bookingContainer) bookingContainer.style.display = 'none';
        if(invalidLinkContainer) {
            invalidLinkContainer.style.display = 'block';
            const p = invalidLinkContainer.querySelector('p');
            if (p) p.textContent = message;
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
        bookingContainer.style.display = 'flex';
    }

    // --- POZOSTAŁE FUNKCJE ---
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

    function checkFormValidity() {
        const isBaseFormValid = baseFormFields.every(field => field.checkValidity());
        let isClassValid = classGroup.style.display === 'none' || schoolClassSelect.checkValidity();
        let isLevelValid = levelGroup.style.display === 'none' || schoolLevelSelect.checkValidity();
        let isTutorValid = tutorGroup.style.display === 'none' || (tutorSelect.value !== "");
        let isTermsAccepted = termsCheckbox ? termsCheckbox.checkValidity() : false;
        reserveButton.disabled = !(isBaseFormValid && isClassValid && isLevelValid && isTutorValid && isTermsAccepted && selectedSlotId !== null);
    }
    
    function showStatus(message, type) {
        reservationStatus.textContent = message;
        reservationStatus.className = `reservation-status ${type}`;
        reservationStatus.style.display = 'block';
        setTimeout(() => {
            reservationStatus.style.display = 'none';
        }, 5000);
    }

    function getFormattedDate(date) {
        const yyyy = date.getFullYear();
        const mm = String(date.getMonth() + 1).padStart(2, '0');
        const dd = String(date.getDate()).padStart(2, '0');
        return `${yyyy}-${mm}-${dd}`;
    }

    function getMonday(d) {
        d = new Date(d);
        const day = d.getDay();
        const diff = d.getDate() - day + (day === 0 ? -6 : 1);
        return new Date(d.setDate(diff));
    }
    
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
        renderCalendarViews(currentWeekStart);
        checkFormValidity();
    }
    
    function selectSlot(slotId, element, date, time) {
        // Usuwamy klasę 'selected' ze wszystkich elementów
        const prevSelected = document.querySelectorAll('.time-block.selected');
        prevSelected.forEach(block => block.classList.remove('selected'));
        
        // Zaznaczamy wszystkie pasujące bloki (w obu widokach)
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
    
    function updateTutorList(newTutors) {
        const currentTutorsInSelect = Array.from(tutorSelect.options).map(o => o.value).filter(v => v);
        if (JSON.stringify(newTutors.sort()) === JSON.stringify(currentTutorsInSelect.sort())) return;
        tutorSelect.innerHTML = '<option value="">Wybierz korepetytora</option>';
        newTutors.forEach(tutor => {
            const option = document.createElement('option');
            option.value = tutor;
            option.textContent = tutor;
            tutorSelect.appendChild(option);
        });
    }

    function renderCalendarViews(startDate) {
        // Usuwamy stary kalendarz (PC)
        calendarContainer.innerHTML = '';
        calendarContainer.className = 'time-slot-calendar';

        // Czyścimy mobilny kontener
        const mobileContainer = document.getElementById('calendar-mobile-container');
        if (mobileContainer) mobileContainer.innerHTML = '';

        generatePCGridCalendar(startDate);
        generateMobileListCalendar(startDate);

        // Inicjalizacja przycisków dla PC
        const pcPrev = calendarContainer.querySelector('#prevWeek');
        const pcNext = calendarContainer.querySelector('#nextWeek');
        if (pcPrev) pcPrev.addEventListener('click', () => changeWeek(-7));
        if (pcNext) pcNext.addEventListener('click', () => changeWeek(7));

        // Inicjalizacja przycisków dla Mobile (jeśli zostały wygenerowane)
        const mobilePrev = mobileContainer ? mobileContainer.querySelector('#mobilePrevWeek') : null;
        const mobileNext = mobileContainer ? mobileContainer.querySelector('#mobileNextWeek') : null;
        if (mobilePrev) mobilePrev.addEventListener('click', () => changeWeek(-7));
        if (mobileNext) mobileNext.addEventListener('click', () => changeWeek(7));
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
            <button id="prevWeek">Poprzedni tydzień</button>
            <h3>${firstDayFormatted} - ${lastDayFormatted}</h3>
            <button id="nextWeek">Następny tydzień</button>
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
                const blockId = `block_${formattedDate}_${timeSlot.replace(':', '')}`;
                
                const daySlots = availableSlotsData[formattedDate] || [];
                const matchingSlot = daySlots.find(slot => slot.time === timeSlot);
                
                const block = document.createElement('div');
                block.className = 'time-block';
                block.dataset.slotId = blockId;
                block.dataset.date = formattedDate;
                block.dataset.time = timeSlot;
                
                let isClickable = false;
                
                const blockDateTime = new Date(`${formattedDate}T${timeSlot}:00`);
    
                if (matchingSlot && blockDateTime > twelveHoursFromNow) {
                    block.textContent = timeSlot;
                    isClickable = true;
                } else {
                    block.classList.add('disabled');
                    if (matchingSlot) { 
                         block.textContent = timeSlot;
                         block.title = "Tego terminu nie można już zarezerwować (mniej niż 12h).";
                    }
                }
    
                if(selectedSlotId === blockId) {
                    block.classList.add('selected');
                }
                
                if(isClickable) {
                    block.addEventListener('click', (e) => selectSlot(blockId, e.target, formattedDate, timeSlot));
                }
                
                cell.appendChild(block);
            });
    
            currentTime.setMinutes(currentTime.getMinutes() + 70);
        }
        
        calendarContainer.appendChild(table);
    }

    function generateMobileListCalendar(startDate) {
        const mobileContainer = document.getElementById('calendar-mobile-container');
        if (!mobileContainer) return;

        const daysInWeek = Array.from({length: 7}, (_, i) => {
            const d = new Date(startDate);
            d.setDate(d.getDate() + i);
            return d;
        });

        // 1. Nawigacja
        const calendarNavigation = document.createElement('div');
        calendarNavigation.className = 'calendar-navigation';
        const firstDayFormatted = `${dayNamesFull[daysInWeek[0].getDay()].substring(0,3)}. ${daysInWeek[0].getDate()} ${monthNames[daysInWeek[0].getMonth()].substring(0,3)}.`;
        const lastDayFormatted = `${dayNamesFull[daysInWeek[6].getDay()].substring(0,3)}. ${daysInWeek[6].getDate()} ${monthNames[daysInWeek[6].getMonth()].substring(0,3)}.`;
        calendarNavigation.innerHTML = `
            <button id="mobilePrevWeek">Poprzedni tydzień</button>
            <h3>${firstDayFormatted} - ${lastDayFormatted}</h3>
            <button id="mobileNextWeek">Następny tydzień</button>
        `;
        mobileContainer.appendChild(calendarNavigation);

        const twelveHoursFromNow = new Date();
        twelveHoursFromNow.setHours(twelveHoursFromNow.getHours() + 12);
        let hasAvailableSlots = false;

        // 2. Lista dni
        daysInWeek.forEach(day => {
            const formattedDate = getFormattedDate(day);
            const daySlots = availableSlotsData[formattedDate] || [];
            
            const availableDaySlots = daySlots.filter(slot => {
                const blockDateTime = new Date(`${formattedDate}T${slot.time}:00`);
                return blockDateTime > twelveHoursFromNow;
            });

            if (availableDaySlots.length === 0) {
                return;
            }
            hasAvailableSlots = true;

            const dayCard = document.createElement('div');
            dayCard.className = 'mobile-day-card';
            dayCard.innerHTML = `<h4>${dayNamesFull[day.getDay()]} ${day.getDate()} ${monthNames[day.getMonth()]}</h4>`;
            
            const slotsContainer = document.createElement('div');
            slotsContainer.className = 'mobile-slots-container';

            availableDaySlots.sort((a, b) => a.time.localeCompare(b.time));

            availableDaySlots.forEach(slot => {
                const blockId = `block_${formattedDate}_${slot.time.replace(':', '')}`;
                
                // Sprawdzamy, czy slot jest aktualnie zaznaczony
                const isCurrentlySelected = selectedSlotId === blockId;

                const block = document.createElement('div');
                block.className = `time-block ${isCurrentlySelected ? 'selected' : ''}`;
                block.dataset.slotId = blockId;
                block.dataset.date = formattedDate;
                block.dataset.time = slot.time;
                block.textContent = slot.time;

                block.addEventListener('click', (e) => selectSlot(blockId, e.target, formattedDate, slot.time));
                slotsContainer.appendChild(block);
            });

            dayCard.appendChild(slotsContainer);
            mobileContainer.appendChild(dayCard);
        });

        if (!hasAvailableSlots) {
            mobileContainer.innerHTML += '<p style="padding: 2rem; text-align: center; color: var(--text-medium);">Brak dostępnych terminów w tym tygodniu.</p>';
        }
    }


    async function fetchAvailableSlots(startDate) {
        const selectedSchoolType = schoolTypeSelect.value;
        const selectedLevel = schoolLevelSelect.value;
        const selectedSubject = subjectSelect.value;
        
        if (!selectedSchoolType || !selectedSubject || (levelGroup.style.display === 'block' && !selectedLevel)) {
            const placeholder = '<div class="calendar-placeholder"><p style="padding: 2rem; text-align: center; color: var(--text-medium);">Proszę wybrać przedmiot, typ szkoły i poziom, aby zobaczyć dostępne terminy.</p></div>';
            calendarContainer.innerHTML = placeholder;
            const mobileContainer = document.getElementById('calendar-mobile-container');
            if (mobileContainer) mobileContainer.innerHTML = placeholder;
            availableSlotsData = {};
            updateTutorList([]);
            return;
        }

        const loadingHTML = '<div class="calendar-placeholder"><p style="padding: 2rem; text-align: center; color: var(--text-medium);">Ładowanie dostępnych terminów...</p></div>';
        calendarContainer.innerHTML = loadingHTML;
        const mobileContainer = document.getElementById('calendar-mobile-container');
        if (mobileContainer) mobileContainer.innerHTML = loadingHTML;
        
        try {
            const params = new URLSearchParams({
                startDate: getFormattedDate(startDate),
                schoolType: selectedSchoolType,
                schoolLevel: selectedLevel || '',
                subject: selectedSubject
            });
            
            const response = await fetch(`${API_BASE_URL}/api/get-schedule?${params.toString()}`);
            if (!response.ok) { throw new Error('Błąd pobierania danych z serwera'); }
            const scheduleFromApi = await response.json();
            
            const processedData = {};
            const uniqueTutors = new Set();
            
            scheduleFromApi.forEach(slot => {
                const { date, time, tutor } = slot;
                if (!processedData[date]) { processedData[date] = []; }
                processedData[date].push({ id: `block_${date}_${time.replace(':', '')}_${tutor.replace(' ', '_')}`, time: time, tutor: tutor, duration: 60 });
                uniqueTutors.add(tutor);
            });
            availableSlotsData = processedData;
            updateTutorList(Array.from(uniqueTutors));

            renderCalendarViews(startDate);

        } catch (error) {
            console.error('Nie udało się pobrać grafiku:', error);
            showStatus('Błąd ładowania grafiku. Spróbuj ponownie później.', 'error');
        }
    }
    
    function initializeEventListeners() {
        reservationForm.addEventListener('change', (event) => {
            const targetId = event.target.id;
            if (['subject', 'schoolType', 'schoolLevel'].includes(targetId)) {
                if (targetId === 'schoolType') {
                    updateSchoolDependentFields();
                }
                fetchAvailableSlots(currentWeekStart);
            } else if (targetId === 'chooseTutorCheckbox' || targetId === 'tutorSelect') {
                handleTutorSelection();
            }
            checkFormValidity();
            calculateAndDisplayPrice(); // <-- Dodane wywołanie
        });
        
        reservationForm.addEventListener('input', () => {
            checkFormValidity();
            calculateAndDisplayPrice(); // <-- Dodane wywołanie
        });

        // Event listener dla checkboxa polityki prywatności
        if (termsCheckbox) {
            termsCheckbox.addEventListener('change', checkFormValidity);
        }

        reserveButton.addEventListener('click', async (e) => {
            e.preventDefault();
            if (!reservationForm.checkValidity() || !selectedSlotId) {
                showStatus('Proszę wypełnić wszystkie wymagane pola i wybrać termin.', 'error');
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
                privacyPolicyAccepted: termsCheckbox.checked
            };
            
            reserveButton.disabled = true;
            reserveButton.textContent = 'Rezerwuję...';

            try {
                const response = await fetch(`${API_BASE_URL}/api/create-reservation`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(formData),
                });
                
                if (response.ok) {
                    const result = await response.json();
                    const params = new URLSearchParams({
                        date: formData.selectedDate,
                        time: formData.selectedTime,
                        teamsUrl: encodeURIComponent(result.teamsUrl),
                        token: result.managementToken,
                        clientID: result.clientID,
                        isTest: result.isTest,
                        isCyclic: result.isCyclic,
                        tutorName: result.tutorName
                    });
                    window.location.href = `confirmation.html?${params.toString()}`;
                } else {
                    console.error("Odpowiedź z serwera nie była OK:", response);
                    const errorData = await response.json().catch(() => ({ error: 'Nieznany błąd' }));
                    showStatus(errorData.error || `Błąd rezerwacji: ${response.statusText}`, 'error');
                }
            } catch (error) {
                console.error('Błąd rezerwacji:', error);
                showStatus('Wystąpił błąd podczas komunikacji z serwerem.', 'error');
            } finally {
                reserveButton.disabled = false;
                reserveButton.textContent = 'Zarezerwuj testową lekcję';
                checkFormValidity();
            }
        });
    }

            }
        });
    }

    // --- Start aplikacji ---
    initializeApp();
});

// Funkcje pomocy
function openHelpModal() {
    document.getElementById('helpModal').classList.add('show');
}

function closeHelpModal() {
    document.getElementById('helpModal').classList.remove('show');
}

// Zamknij modal po kliknięciu gdzie indziej
document.addEventListener('click', function(event) {
    const modal = document.getElementById('helpModal');
    if (modal && event.target == modal) {
        modal.classList.remove('show');
    }
});
