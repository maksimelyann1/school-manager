export function getSearchVariations(query) {
    if (!query) return [''];
    
    const q = query.toLowerCase();
    const variations = new Set([q]);

    const enLayout = "qwertyuiop[]asdfghjkl;'zxcvbnm,./";
    const ukLayout = "йцукенгшщзхїфівапролджєячсмитьбю.";
    
    const switchLayout = (str, from, to) => {
        let res = '';
        for (let char of str) {
            const idx = from.indexOf(char);
            res += idx !== -1 ? to[idx] : char;
        }
        return res;
    };

    const toUk = switchLayout(q, enLayout, ukLayout);
    const toEn = switchLayout(q, ukLayout, enLayout);
    variations.add(toUk);
    variations.add(toEn);

    const translitMap = {
        'а':'a','б':'b','в':'v','г':'g','ґ':'g','д':'d','е':'e','є':'ye','ж':'zh',
        'з':'z','и':'y','і':'i','ї':'yi','й':'y','к':'k','л':'l','м':'m','н':'n',
        'о':'o','п':'p','р':'r','с':'s','т':'t','у':'u','ф':'f','х':'h','ц':'ts',
        'ч':'ch','ш':'sh','щ':'shch','ь':'','ю':'yu','я':'ya'
    };
    
    const reverseTranslitMap = {
        'a':'а','b':'б','c':'ц','d':'д','e':'е','f':'ф','g':'г','h':'х','i':'і',
        'j':'дж','k':'к','l':'л','m':'м','n':'н','o':'о','p':'п','q':'к','r':'р',
        's':'с','t':'т','u':'у','v':'в','w':'в','x':'кс','y':'й','z':'з'
    };

    const applyMap = (str, map) => {
        let res = '';
        for (let char of str) {
            res += map[char] !== undefined ? map[char] : char;
        }
        return res;
    };

    const translitEn = applyMap(q, translitMap);
    const translitUk = applyMap(q, reverseTranslitMap);
    
    variations.add(translitEn);
    variations.add(translitUk);
    variations.add(applyMap(toUk, translitMap));
    variations.add(applyMap(toEn, reverseTranslitMap));

    return Array.from(variations).filter(v => v.trim() !== '');
}
