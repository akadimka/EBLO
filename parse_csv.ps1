$headers = 'file_path,metadata_authors,proposed_author,author_source,metadata_series,proposed_series,series_source,file_title'
$line = 'Волков Тим\Пленники Зоны. Кровь цвета хаки.fb2,Сергей Коротков; Тим Волков,Волков Тим,folder_dataset,Пленники Зоны,,,Кровь цвета хаки'

$header_cols = $headers -split ','
$data_cols = $line -split ','

Write-Host "Total columns: $($header_cols.Length)"
Write-Host ""

for ($i=0; $i -lt [Math]::Max($header_cols.Length, $data_cols.Length); $i++) {
    $h = if ($i -lt $header_cols.Length) { $header_cols[$i] } else { "??" }
    $v = if ($i -lt $data_cols.Length) { $data_cols[$i] } else { "[missing]" }
    $v_display = if ($v -eq "") { "[EMPTY]" } else { $v }
    Write-Host "[$($i+1:D2}] $h`: '$v_display'"
}
