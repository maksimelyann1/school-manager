const DB_NAME = 'SchoolManagerDB';
const DB_VERSION = 1;
const STORE_NAME = 'historyFiles';

export const initDB = () => {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open(DB_NAME, DB_VERSION);

        request.onerror = () => reject(request.error);
        request.onsuccess = () => resolve(request.result);

        request.onupgradeneeded = (e) => {
            const db = e.target.result;
            if (!db.objectStoreNames.contains(STORE_NAME)) {
                db.createObjectStore(STORE_NAME, { keyPath: 'id' });
            }
        };
    });
};

export const saveFilesToDB = async (id, files) => {
    const db = await initDB();
    return new Promise((resolve, reject) => {
        const transaction = db.transaction([STORE_NAME], 'readwrite');
        const store = transaction.objectStore(STORE_NAME);
        const request = store.put({ id, files });

        request.onsuccess = () => resolve();
        request.onerror = () => reject(request.error);
    });
};

export const getFilesFromDB = async (id) => {
    const db = await initDB();
    return new Promise((resolve, reject) => {
        const transaction = db.transaction([STORE_NAME], 'readonly');
        const store = transaction.objectStore(STORE_NAME);
        const request = store.get(id);

        request.onsuccess = () => resolve(request.result ? request.result.files : []);
        request.onerror = () => reject(request.error);
    });
};

export const deleteOldFilesFromDB = async (validIds) => {
    const db = await initDB();
    return new Promise((resolve, reject) => {
        const transaction = db.transaction([STORE_NAME], 'readwrite');
        const store = transaction.objectStore(STORE_NAME);
        const request = store.getAllKeys();
        const validIdSet = new Set(validIds);

        request.onsuccess = () => {
            const keys = request.result;
            keys.forEach(key => {
                if (!validIdSet.has(key)) {
                    store.delete(key);
                }
            });
        };
        request.onerror = () => reject(request.error);
        transaction.oncomplete = () => resolve();
        transaction.onerror = () => reject(transaction.error);
    });
};
