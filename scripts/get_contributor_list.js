(async function get_contributors(){
    let all_contributors = [];
    for (let i = 1; i < 11; i++){
        const response = await fetch(`https://api.github.com/repos/cecli-dev/cecli/contributors?anon=1&per_page=100&page=${i}`);
        const data = await response.json();

        all_contributors = all_contributors.concat(data)
    }


    let output = [];

    all_contributors.forEach((item) => {
        if(item.login){
            output.push(`<a href="https://github.com/cecli-dev/cecli/commits/main?author=${item.login}">@${item.login}</a>`)
        }else{
            output.push(`${item.name}`)
        }
    });

    // Create 4-column HTML table
    let table = '<table>\n<tbody>\n';
    
    for (let i = 0; i < output.length; i += 4) {
        table += '<tr>\n';
        for (let j = 0; j < 4; j++) {
            table += '<td>';
            if (i + j < output.length) {
                table += output[i + j];
            }
            table += '</td>\n';
        }
        table += '</tr>\n';
    }
    
    table += '</tbody>\n</table>';
    console.log(table);
})()