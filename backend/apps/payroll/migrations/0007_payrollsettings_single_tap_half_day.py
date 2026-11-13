# G17-1 (13 Nov 2026): one tap in a day = ½ day unpaid, when the company turns it on

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payroll', '0006_alter_payrollsettings_meal_late_after'),
    ]

    operations = [
        migrations.AddField(
            model_name='payrollsettings',
            name='single_tap_half_day',
            field=models.BooleanField(default=False, verbose_name='Tap sekali = potong ½ hari'),
        ),
    ]
