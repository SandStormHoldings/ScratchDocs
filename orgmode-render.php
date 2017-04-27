#!/usr/bin/env php
<?
require_once('orgile/www/site/orgile/orgile.php');
$fp = fopen('php://stdin', 'r');
$cont='';
while ($line = fgets($fp))
    {
        $cont.= $line;
    }
$op = orgile($cont);
echo $op;

?>