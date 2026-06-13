nomes=(vulcan kronos risa terra)
portos=(11111 22222 33333 44444 55555)
for i in 0 1 2 3 
do
    log="log.${nomes[i]}"
    date "+DATE: %Y-%m-%d   TIME: %H:%M:%S%n" > $log
    python3 ../esqueleto_roteador.py ${portos[i]}  &> $log &
done 
sleep 1 
python3 ../controle.py ../roteadores_locais.txt < comandos.txt | tee log.controle
